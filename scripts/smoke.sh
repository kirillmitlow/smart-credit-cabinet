#!/usr/bin/env bash
# T-515 / TS-001: readiness and Sokolova's happy path. Bash 3.2 / Git Bash / WSL.
set -euo pipefail

SCRIPT_DIR=$(cd -- "${BASH_SOURCE[0]%/*}" && pwd)
# shellcheck source=lib/smoke-json.sh
source "$SCRIPT_DIR/lib/smoke-json.sh"

fail() { printf 'SMOKE FAIL: %s\n' "$*" >&2; exit 1; }
say() { printf 'SMOKE: %s\n' "$*"; }
usage() {
    cat <<'HELP'
Usage: bash scripts/smoke.sh [--quick] [--timeout SECONDS] [--api-url URL] [WEB_URL]
Default WEB_URL: http://127.0.0.1:8080; API: WEB_URL/api.
--quick checks readiness only; full mode RESETS ONLY sokolova and issues a demo loan.
--api-url selects a directly exposed API (without /api).
--no-mock-ports skips direct mock probes (cloud: mock ports are private).
Local mock URLs: SMOKE_REGISTRY_URL, SMOKE_TAX_URL, SMOKE_BKI_URL,
SMOKE_BANK_CORE_URL, SMOKE_SCENARIOS_URL (defaults: 127.0.0.1:8101..8105).
Remote WEB_URL skips direct mock probes automatically; the full path checks integrations.
Requires Bash, curl and standard mktemp/rm/sleep; no jq, Python, Node or Docker CLI.
HELP
}

QUICK=0 TIMEOUT=90 WEB_URL=http://127.0.0.1:8080 API_URL= MOCK_PORTS=auto
POSITIONAL=0
while (( $# )); do
    case "$1" in
        --quick) QUICK=1 ;;
        --no-mock-ports) MOCK_PORTS=0 ;;
        --timeout|--api-url)
            (( $# >= 2 )) || fail "Missing value for $1"
            if [[ $1 == --timeout ]]; then TIMEOUT=$2; else API_URL=$2; fi
            shift
            ;;
        --help|-h) usage; exit 0 ;;
        --*) fail "Unknown option: $1" ;;
        *) (( POSITIONAL == 0 )) || fail 'Only one WEB_URL is allowed'; WEB_URL=$1; POSITIONAL=1 ;;
    esac
    shift
done
[[ $TIMEOUT =~ ^[1-9][0-9]{0,3}$ ]] || fail '--timeout must be an integer from 1 to 9999'
WEB_URL=${WEB_URL%/}
API_URL=${API_URL:-$WEB_URL/api}
API_URL=${API_URL%/}
validate_url() {
    [[ $1 =~ ^https?://[^/?#@[:space:]]+(/[^?#@[:space:]]*)?$ ]] ||
        fail 'Expected an http(s) URL without credentials, query or fragment'
}
validate_url "$WEB_URL"
validate_url "$API_URL"
if [[ $MOCK_PORTS == auto ]]; then
    case "$WEB_URL" in
        http://127.0.0.1|http://localhost|http://127.0.0.1:*|http://localhost:*|https://127.0.0.1:*|https://localhost:*) MOCK_PORTS=1 ;;
        *) MOCK_PORTS=0 ;;
    esac
fi
command -v curl >/dev/null || fail 'curl is not installed'
TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/scc-smoke.XXXXXX") || fail 'Cannot create temporary directory'
trap 'rm -rf -- "$TMP_DIR"' EXIT
trap 'exit 1' INT TERM
COOKIE_JAR=$TMP_DIR/cookies
: > "$COOKIE_JAR"

# No automatic POST retry or redirect: an uncertain write must not issue another loan.
request() {
    local method=$1 url=$2 body=${3:-} remaining=${4:-30} packed
    local args=(--silent --show-error --connect-timeout 3 --max-time "$remaining"
        --request "$method" --cookie "$COOKIE_JAR" --cookie-jar "$COOKIE_JAR"
        --header 'Accept: application/json' --write-out $'\n%{http_code}')
    if [[ -n $body ]]; then args+=(--header 'Content-Type: application/json' --data "$body"); fi
    HTTP_BODY= HTTP_STATUS=000
    # Suppress transport diagnostics: URLs/headers may contain private cloud settings.
    if ! packed=$(curl "${args[@]}" "$url" 2>"$TMP_DIR/curl-error"); then return 1; fi
    HTTP_STATUS=${packed##*$'\n'}
    HTTP_BODY=${packed%$'\n'*}
}
field() {
    json_read "$HTTP_BODY" "$1" || fail "Missing or invalid JSON field: $1"
}
problem_code() {
    PROBLEM_CODE=UNKNOWN
    if json_read "$HTTP_BODY" code && [[ $JSON_TEXT =~ ^[A-Z][A-Z0-9_]*$ ]]; then
        PROBLEM_CODE=$JSON_TEXT
    fi
}
api() {
    local method=$1 path=$2 body=${3:-}
    request "$method" "$API_URL$path" "$body" || fail "$method $path: connection failed or timed out"
    if [[ $HTTP_STATUS != 2?? ]]; then
        problem_code
        fail "$method $path: HTTP $HTTP_STATUS ($PROBLEM_CODE)"
    fi
}
ready() {
    local name=$1 url=$2 kind=$3 deadline=$((SECONDS + TIMEOUT)) left
    validate_url "$url"
    while :; do
        left=$((deadline - SECONDS))
        (( left > 0 )) || fail "$name not ready within ${TIMEOUT}s (HTTP $HTTP_STATUS)"
        if request GET "$url" '' "$left" && [[ $HTTP_STATUS == 200 ]]; then
            if [[ $kind == web && $HTTP_BODY == ok* ]]; then break; fi
            if [[ $kind == json ]] && json_read "$HTTP_BODY" status && [[ $JSON_TEXT == ok ]]; then break; fi
            if [[ $kind == worker ]] && json_read "$HTTP_BODY" worker.stale && [[ $JSON_TEXT == false ]]; then break; fi
        fi
        sleep 1
    done
    say "$name ready"
}

ready web "$WEB_URL/healthz" web
ready api "$API_URL/health/ready" json
if [[ $MOCK_PORTS == 1 ]]; then
    ready mock-registry "${SMOKE_REGISTRY_URL:-http://127.0.0.1:8101}/health/ready" json
    ready mock-tax "${SMOKE_TAX_URL:-http://127.0.0.1:8102}/health/ready" json
    ready mock-credit-bureau "${SMOKE_BKI_URL:-http://127.0.0.1:8103}/health/ready" json
    ready mock-bank-core "${SMOKE_BANK_CORE_URL:-http://127.0.0.1:8104}/health/ready" json
    ready mock-scenarios "${SMOKE_SCENARIOS_URL:-http://127.0.0.1:8105}/health/ready" json
else
    say 'Direct mock probes disabled (private ports); full mode verifies the integration path'
fi
ready worker "$API_URL/health/deps" worker
if (( QUICK )); then say 'PASS: readiness (no data changed)'; exit 0; fi

say 'Resetting only demo persona sokolova'
deadline=$((SECONDS + TIMEOUT))
while :; do
    remaining=$((deadline - SECONDS))
    (( remaining > 0 )) || fail "sokolova reset busy for ${TIMEOUT}s"
    request POST "$API_URL/demo/personas/sokolova/reset" '' "$remaining" || fail 'sokolova reset: connection failed or timed out'
    [[ $HTTP_STATUS == 200 ]] && break
    problem_code
    [[ $HTTP_STATUS == 409 && $PROBLEM_CODE == DEMO_RESET_IN_PROGRESS ]] ||
        fail "sokolova reset: HTTP $HTTP_STATUS ($PROBLEM_CODE)"
    sleep 1
done
field status
[[ $JSON_TEXT == DONE ]] || fail 'sokolova reset did not finish'

api GET /auth/roles/001234567887
field company.id; company=$JSON_TEXT
field people.0.userId; user=$JSON_TEXT
[[ $company =~ ^[0-9a-fA-F-]{36}$ && $user =~ ^[0-9a-fA-F-]{36}$ ]] || fail 'Invalid login identifiers'
api POST /auth/request-code "{\"userId\":\"$user\",\"companyId\":\"$company\"}"
field requestId; challenge=$JSON_RAW
field demoCode; code=$JSON_RAW
[[ $code != null && $code != '""' ]] || fail 'No demo login code: DEMO_MODE must be enabled'
api POST /auth/verify-code "{\"requestId\":$challenge,\"code\":$code}"
field activeCompanyId
if [[ $JSON_TEXT != "$company" ]]; then api PUT /me/active-company "{\"companyId\":\"$company\"}"; fi
say 'Demo login complete'

api POST /wizard/recommendations '{"answers":{"purpose":"EQUIPMENT","amountRub":500000,"frequency":"ONCE","paybackHorizon":"MONTHS_3_12","govContract":"NO"}}'
field applicationId; application=$JSON_TEXT
[[ $application =~ ^[0-9a-fA-F-]{36}$ ]] || fail 'Wizard did not create an application'
api GET "/applications/$application"
field version; version=$JSON_RAW
api PATCH "/applications/$application/draft" "{\"version\":$version,\"productCode\":\"EXPRESS\",\"amountRub\":500000,\"termMonths\":12}"

api GET "/applications/$application/consents"
consents=$HTTP_BODY items= separator= index=0
while json_read "$consents" "items.$index"; do
    json_read "$consents" "items.$index.canSign" || fail 'Invalid consent permissions'
    if [[ $JSON_TEXT == true ]]; then
        json_read "$consents" "items.$index.status" || fail 'Missing consent status'
        if [[ $JSON_TEXT != SIGNED ]]; then
            json_read "$consents" "items.$index.kind" || fail 'Missing consent kind'; kind=$JSON_RAW
            json_read "$consents" "items.$index.subjectInn" || fail 'Missing consent subject'; subject=$JSON_RAW
            items+="$separator{\"kind\":$kind,\"subjectInn\":$subject}"
            separator=,
        fi
    fi
    index=$((index + 1))
done
[[ -n $items ]] || fail 'No signable consents for sokolova'
api POST "/applications/$application/consents" "{\"items\":[$items],\"acceptPepRules\":true}"
field requestId; challenge=$JSON_RAW
field demoCode; code=$JSON_RAW
field items; items=$JSON_RAW
api POST "/applications/$application/consents/sign" "{\"requestId\":$challenge,\"code\":$code,\"items\":$items}"
api GET "/applications/$application/consents"
field allSigned
[[ $JSON_TEXT == true ]] || fail 'Consents not fully signed'
api POST "/applications/$application/submit"

wait_status() {
    local wanted=$1 deadline=$((SECONDS + TIMEOUT)) last= remaining
    while :; do
        remaining=$((deadline - SECONDS))
        (( remaining > 0 )) || fail "Expected $wanted within ${TIMEOUT}s; last status: $last"
        request GET "$API_URL/applications/$application" '' "$remaining" || fail 'Application poll: connection failed or timed out'
        [[ $HTTP_STATUS == 200 ]] || fail "Application poll: HTTP $HTTP_STATUS"
        field status
        if [[ $JSON_TEXT != "$last" ]]; then last=$JSON_TEXT; say "Application: $last"; fi
        [[ $last == "$wanted" ]] && return 0
        case "$last" in
            REJECTED|COUNTER_OFFER|NEEDS_INFO|MANUAL_REVIEW|WITHDRAWN|EXPIRED|DISBURSED)
                fail "Expected $wanted; got $last (check demo sources and worker)" ;;
        esac
        sleep 1
    done
}
wait_status APPROVED
api GET "/applications/$application/offer"
offer_body=$HTTP_BODY
field id; offer=$JSON_TEXT
[[ $offer =~ ^[0-9a-fA-F-]{36}$ ]] || fail 'Invalid offer id'
index=0 variant=
while json_read "$offer_body" "variants.$index"; do
    json_read "$offer_body" "variants.$index.recommended" || fail 'Invalid offer variant'
    if [[ $JSON_TEXT == true ]]; then
        json_read "$offer_body" "variants.$index.id" || fail 'Missing recommended variant id'
        variant=$JSON_RAW
        break
    fi
    index=$((index + 1))
done
[[ -n $variant ]] || fail 'No recommended offer'
api POST "/offers/$offer/accept" "{\"variantId\":$variant}"
field contract.id; contract=$JSON_TEXT
[[ $contract =~ ^[0-9a-fA-F-]{36}$ ]] || fail 'Invalid contract id'
api POST "/contracts/$contract/sign/request" '{"agree":true,"acceptPepRules":true}'
field requestId; challenge=$JSON_RAW
field demoCode; code=$JSON_RAW
api POST "/contracts/$contract/sign" "{\"requestId\":$challenge,\"code\":$code}"
wait_status DISBURSED
say 'PASS: sokolova APPROVED -> signed -> DISBURSED (demo loan: 500000 RUB)'
