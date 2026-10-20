"""CPU-only scoring adapters. No generate(), no inference API, no product logic."""
import gc
import json
import os
import random
import time

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np
import torch
from sklearn.model_selection import StratifiedKFold
from torch import nn
from transformers import AutoModel, AutoModelForCausalLM, AutoModelForSequenceClassification, AutoTokenizer

from common import LABELS, ROOT, SCHEMA, SLOTS, gold, model_path

THREADS = 4
MAX_LENGTH = 192
torch.set_num_threads(THREADS)
torch.set_num_interop_threads(1)

INSTRUCTION = (
    "Извлеки только то, что прямо сказано в тексте предпринимателя. "
    "Не додумывай отсутствующие сведения: для них выбирай UNKNOWN, а для неясной цели OTHER. "
    "Финансирование ещё не выполненного заказа отличается от текущей нехватки денег при задержке выручки. "
    "Покупка оборудования сама по себе не означает согласие заложить его. "
)
QUESTIONS = {
    "purpose": "На что именно предпринимателю нужны деньги?",
    "frequency": "Сказано ли, что финансирование разовое или повторяется?",
    "payback_horizon": "Через сколько вернутся деньги или закончится нехватка? Не путай со сроком получения кредита.",
    "urgency": "Насколько срочно нужно получить деньги?",
    "gov_contract": "Указан ли государственный или муниципальный контракт либо прямо сказано, что его нет?",
    "collateral": "Какой залог предприниматель прямо готов предоставить?",
}


class Embedding:
    def __init__(self, candidate, examples):
        self.candidate = candidate
        path = model_path(candidate)
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.model = AutoModel.from_pretrained(path, local_files_only=True).to("cpu").eval()
        self.reference = self.encode([r["text"] for r in examples])
        self.targets = {s: gold(examples, s) for s in SLOTS}
        self.k = 1

    @torch.inference_mode()
    def encode(self, texts):
        vectors = []
        for start in range(0, len(texts), 8):
            batch = self.tokenizer([self.candidate["prefix"] + t for t in texts[start:start + 8]],
                                   return_tensors="pt", truncation=True, padding=True, max_length=MAX_LENGTH)
            output = self.model(**batch).last_hidden_state
            if self.candidate["pool"] == "cls":
                v = output[:, 0]
            else:
                mask = batch["attention_mask"].unsqueeze(-1)
                v = (output * mask).sum(1) / mask.sum(1)
            vectors.append(torch.nn.functional.normalize(v, dim=-1).numpy())
        return np.concatenate(vectors)

    def scores_from_vector(self, vector, k=None):
        sims = vector @ self.reference.T
        scores = {}
        for slot in SLOTS:
            columns = []
            for i in range(len(LABELS[slot])):
                values = np.sort(sims[:, self.targets[slot] == i], axis=1)
                count = min(k or self.k, values.shape[1])
                if count == 0:
                    raise ValueError(f"No support example for {slot}/{i}")
                columns.append(values[:, -count:].mean(axis=1))
            scores[slot] = np.stack(columns, axis=1)
        return scores

    def score(self, text):
        return {s: x[0] for s, x in self.scores_from_vector(self.encode([text])).items()}


class PairScorer:
    def __init__(self, candidate):
        self.kind = candidate["kind"]
        path = model_path(candidate)
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True).to("cpu").eval()
        self.entailment = next((int(i) for i, name in self.model.config.id2label.items()
                                if "entail" in name.lower()), 0)
        self.hypotheses = [SCHEMA[s][label] for s in SLOTS for label in LABELS[s]]

    @torch.inference_mode()
    def score(self, text):
        values = []
        for start in range(0, len(self.hypotheses), 8):
            hs = self.hypotheses[start:start + 8]
            inputs = self.tokenizer([text] * len(hs), hs, padding=True, truncation=True,
                                    max_length=MAX_LENGTH, return_tensors="pt")
            logits = self.model(**inputs).logits.float()
            if self.kind == "nli":
                # Entailment evidence against both contradiction and neutral.
                other = [i for i in range(logits.shape[1]) if i != self.entailment]
                values.extend((logits[:, self.entailment] - torch.logsumexp(logits[:, other], dim=1)).tolist())
            else:
                values.extend(logits[:, 0].tolist())
        result, offset = {}, 0
        for slot in SLOTS:
            n = len(LABELS[slot])
            result[slot] = np.array(values[offset:offset + n])
            offset += n
        return result


class Laya:
    def __init__(self, candidate):
        import laya
        self.agent = laya.load(str(model_path(candidate)), device="cpu")
        self.questions = {s: {"type": "choice", "instructions": INSTRUCTION + QUESTIONS[s],
                              "criteria": SCHEMA[s]} for s in SLOTS}

    def score(self, text):
        result = self.agent.predict(text, self.questions)
        return {s: np.log(np.clip([result["answers"][s]["probabilities"][label]
                                  for label in LABELS[s]], 1e-8, 1)) for s in SLOTS}


class LLM:
    def __init__(self, candidate):
        path = model_path(candidate)
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.tokenizer.padding_side = "left"
        cls = AutoModelForCausalLM
        if candidate["kind"] == "llm35":
            from transformers import AutoModelForImageTextToText
            cls = AutoModelForImageTextToText
        self.model = cls.from_pretrained(path, local_files_only=True,
                                        torch_dtype=torch.float32).to("cpu").eval()
        self.answer_tokens = [self.tokenizer.encode(chr(65 + i), add_special_tokens=False) for i in range(6)]
        assert all(len(ids) == 1 for ids in self.answer_tokens), "Option codes must be single tokens"

    @torch.inference_mode()
    def score(self, text):
        # P(A|prompt) etc. is the full sequence likelihood of a one-token option code.
        # Equal answer length avoids length normalization and verbalizer length bias.
        prompts = []
        for slot in SLOTS:
            options = "\n".join(f"{chr(65 + i)}: {label}. {SCHEMA[slot][label]}"
                                for i, label in enumerate(LABELS[slot]))
            content = f"{INSTRUCTION}\nТекст предпринимателя: {text}\nВопрос: {QUESTIONS[slot]}\n{options}\nОтветь только буквой варианта."
            prompts.append(self.tokenizer.apply_chat_template(
                [{"role": "user", "content": content}], tokenize=False, add_generation_prompt=True,
                enable_thinking=False))
        values = {}
        # Small batches limit memory on an 8 GB computer. No sampling or text generation.
        for start in range(0, len(SLOTS), 2):
            batch = self.tokenizer(prompts[start:start + 2], padding=True, return_tensors="pt")
            # Left padding makes the final token real; only compute its vocabulary logits.
            output = self.model(**batch, use_cache=False, logits_to_keep=1).logits
            logits = output[:, -1].float()
            for j, slot in enumerate(SLOTS[start:start + 2]):
                values[slot] = logits[j, [ids[0] for ids in self.answer_tokens[:len(LABELS[slot])]]].numpy()
            del output
        return values


class GLiNER:
    def __init__(self, candidate):
        from gliner2 import AutoExtractor
        self.model = AutoExtractor.from_pretrained(str(model_path(candidate)), map_location="cpu")
        self.model = self.model.to("cpu").float().eval()
        # Request every option, with the same mutually exclusive softmax used for single-label tasks.
        self.tasks = {s: dict(labels=SCHEMA[s], multi_label=True, class_act="softmax", cls_threshold=0,
                              prompt=INSTRUCTION + QUESTIONS[s]) for s in SLOTS}

    @torch.inference_mode()
    def score(self, text):
        output = self.model.classify_text(text, self.tasks, threshold=0, include_confidence=True)
        result = {}
        for s in SLOTS:
            probabilities = {item["label"]: item["confidence"] for item in output[s]}
            assert set(probabilities) == set(LABELS[s]), "GLiNER must return all options"
            result[s] = np.log(np.clip([probabilities[label] for label in LABELS[s]], 1e-12, 1))
        return result


class MultiTask(nn.Module):
    def __init__(self, path):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(path, local_files_only=True)
        self.heads = nn.ModuleDict({s: nn.Linear(self.encoder.config.hidden_size, len(LABELS[s])) for s in SLOTS})

    def forward(self, inputs):
        x = self.encoder(**inputs).last_hidden_state[:, 0]
        return {s: head(x) for s, head in self.heads.items()}


def fit_multitask(candidate, rows, seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    path = model_path(candidate)
    tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = MultiTask(path).to("cpu")
    optimizer = torch.optim.AdamW([
        {"params": model.encoder.parameters(), "lr": 3e-5},
        {"params": model.heads.parameters(), "lr": 1e-3},
    ], weight_decay=0.01)
    targets = {s: torch.tensor(gold(rows, s)) for s in SLOTS}
    for epoch in range(20):
        model.train()
        order = np.random.permutation(len(rows))
        for start in range(0, len(rows), 8):
            ids = order[start:start + 8]
            batch = tok([rows[i]["text"] for i in ids], padding=True, truncation=True,
                        max_length=MAX_LENGTH, return_tensors="pt")
            outputs = model(batch)
            loss = sum(nn.functional.cross_entropy(outputs[s], targets[s][ids]) for s in SLOTS) / len(SLOTS)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
    return model.eval(), tok


class FineTuned:
    def __init__(self, candidate, checkpoint):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path(candidate), local_files_only=True)
        self.model = MultiTask(model_path(candidate)).to("cpu")
        self.model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
        self.model.eval()

    @torch.inference_mode()
    def score(self, text):
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=MAX_LENGTH)
        return {s: v[0].numpy() for s, v in self.model(inputs).items()}


def train_oof(candidate, rows):
    oof = {s: np.zeros((len(rows), len(LABELS[s]))) for s in SLOTS}
    fold_ids = np.zeros(len(rows), dtype=int)
    started = time.perf_counter()
    splitter = StratifiedKFold(n_splits=3, shuffle=True, random_state=17)
    for fold, (train, val) in enumerate(splitter.split(np.zeros(len(rows)), gold(rows, "purpose"))):
        print("FIT FOLD", fold + 1, flush=True)
        model, tok = fit_multitask(candidate, [rows[i] for i in train], 17 + fold)
        with torch.inference_mode():
            for i in val:
                inputs = tok(rows[i]["text"], return_tensors="pt", truncation=True, max_length=MAX_LENGTH)
                for s, v in model(inputs).items():
                    oof[s][i] = v[0].numpy()
                fold_ids[i] = fold
        del model
        gc.collect()
    print("FIT FINAL", flush=True)
    model, _ = fit_multitask(candidate, rows, 17)
    checkpoint = ROOT / "checkpoints/rubert-finetuned.pt"
    checkpoint.parent.mkdir(exist_ok=True)
    torch.save(model.state_dict(), checkpoint)
    del model
    gc.collect()
    return oof, fold_ids, time.perf_counter() - started


def load(candidate, examples):
    kind = candidate["kind"]
    if kind == "embedding":
        return Embedding(candidate, examples)
    if kind in ("nli", "reranker"):
        return PairScorer(candidate)
    if kind == "laya":
        return Laya(candidate)
    if kind in ("llm", "llm35"):
        return LLM(candidate)
    if kind == "gliner":
        return GLiNER(candidate)
    if kind == "finetuned":
        return FineTuned(candidate, ROOT / "checkpoints/rubert-finetuned.pt")
    raise ValueError(kind)
