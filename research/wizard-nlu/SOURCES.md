# Источники, версии и лицензии

Проверка Hugging Face выполнена 21 октября 2026 года (Новосибирск). Точные SHA ревизий и машинно считанные лицензии сохранены в `model_manifest.json`; отдельная проверка исходных Qwen2.5 — в `upstream_checks.json`. Ссылки ведут на страницы авторов моделей. Веса не входят в PR.

| Кандидат | Модель автора | Лицензия весов по model card |
|---|---|---|
| rubert-knn, rubert-finetuned | [cointegrated/rubert-tiny2](https://huggingface.co/cointegrated/rubert-tiny2) | MIT |
| e5-small | [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) | MIT |
| e5-base | [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base) | MIT |
| user-base | [deepvk/USER-base](https://huggingface.co/deepvk/USER-base) | Apache-2.0 |
| user2-small | [deepvk/USER2-small](https://huggingface.co/deepvk/USER2-small) | Apache-2.0 |
| user2-base | [deepvk/USER2-base](https://huggingface.co/deepvk/USER2-base) | Apache-2.0 |
| laya | [convaiinnovations/laya-multilingual](https://huggingface.co/convaiinnovations/laya-multilingual) | Apache-2.0 |
| nli | [MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7) | MIT |
| bge-reranker | [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | Apache-2.0 |
| qwen3-0.6b | [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) | Apache-2.0 |
| qwen3-1.7b | [Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) | Apache-2.0 |
| qwen3.5-0.8b | [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | Apache-2.0 |
| qwen3.5-2b | [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) | Apache-2.0 |
| gliner-decide | [fastino/GLiNER2.5-multi-Decide](https://huggingface.co/fastino/GLiNER2.5-multi-Decide) | Apache-2.0 |

Испрошенные [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct) и [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) существуют с открытыми весами. Вместо них в замер включены более новые Qwen3 и Qwen3.5 близкого размера. Это **не сравнение поколений на одинаковом числе параметров**: 0.5→0.6→0.8B и 1.5→1.7→2B. Qwen3 оставлены как более простой текстовый CPU-вариант; в Qwen3.5 не используются изображения и генерация.

По [карточке USER2](https://huggingface.co/deepvk/USER2-base), USER2 — новое поколение USER. Поэтому помимо запрошенного USER-base добавлены USER2-small/base. Для E5 используется `query: `, для USER-base также `query: `, для USER2 — рекомендованный авторами префикс классификации `classification: `. Для rubert-tiny2 — CLS pooling, для остальных эмбеддингов — masked mean pooling и L2-нормализация, как в официальных примерах.

GLiNER2.5-multi-Decide — найденный открытый аналог выбора из заданных вариантов: несколько классификаций за один вызов, без генерации. Выбрана multilingual-версия. В GLiNER запрашиваются все метки с `multi_label=True`, но явно используется `class_act="softmax"`, чтобы получить то же распределение взаимоисключающих вариантов; нулевой порог нужен только для возврата всех вероятностей, подстановка контролируется отдельным dev-порогом.

Laya использует официальный [пакет laya](https://pypi.org/project/laya/), GLiNER — официальный [gliner2](https://pypi.org/project/gliner2/). Библиотеки запускаются локально; возможности облачного API GLiNER не вызываются. В Laya увеличен бюджет вопроса до 512 токенов: стандартные 256 обрезали длинные русские инструкции. Общая длина остаётся 1024. Внутреннее ограничение Laya на 48 токенов описания одного варианта сохранено; оно ограничивает полноту длинных описаний и отражено в отчёте.

NLI оценивает entailment против contradiction и neutral для пары «текст, описание варианта». Кросс-энкодер оценивает релевантность той же пары. Это адаптация общего назначения, без обучения под банковские слоты; качество существенно зависит от формулировок. Для Qwen ответом является одна буква варианта A…F: её log-likelihood получается из финальных logits, затем нормируется по допустимым буквам. Все ответы имеют одинаковую длину в один токен. Порядок вариантов фиксирован; влияние порядка и выбора букв отдельно не исследовалось.

Ключевые библиотеки: [PyTorch](https://github.com/pytorch/pytorch/blob/main/LICENSE) (BSD-style), [Transformers](https://github.com/huggingface/transformers/blob/main/LICENSE) (Apache-2.0), [scikit-learn](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING) (BSD-3-Clause), [NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) (BSD-3-Clause), [SciPy](https://github.com/scipy/scipy/blob/main/LICENSE.txt) (BSD-3-Clause). Полный состав зависимостей и артефактов — в двух uv.lock. При распространении самих весов и библиотек нужно сохранить соответствующие лицензии и notices; данный PR распространяет исследовательские тексты и скрипты, а веса загружает отдельно.
