import time
import json
import logging
import requests
import tiktoken

from dataclasses import dataclass
from openai import OpenAI

from app.core.config import settings


# ===================== CONFIG =====================

MODEL = settings.llm_model
TEMPERATURE = 0

PROMPTS = [
    "Дай теги на языке оригинала. 12 шт. по следующему контексту Общая концепция военной обороны описывает, как Бундесвер реагирует на угрозы и какие возможности для этого ему необходимы. Первая немецкая военная стратегия и профиль возможностей Бундесвера (план для вооруженных сил) тесно связаны друг с другом: общая концепция определяет цели, средства и пути их достижения. Поскольку эти документы являются секретными, они публикуются только в виде выдержек.Военная стратегия для Бундесвера описывает ситуацию с угрозами для Германии. В ней подчеркивается, что под угрозой находится все немецкое общество. Такие государства, как Россия, уже сейчас, даже не вступая в открытую войну, предпринимают агрессивные действия. Германия должна быть готова к тому, что границы войны будут размываться. Чтобы эффективно защищать себя и своих союзников, Бундесвер должен развиться в самую сильную конвенциональную армию в Европе. План для вооруженных сил определяет путь к этой цели.Учитывая изменившуюся ситуацию в области безопасности, министр обороны Борис Писториус поручил переработать стратегию резерва. Это необходимо, поскольку без сильного, готового к применению и быстро мобилизуемого резерва Бундесвер не сможет выполнять свою основную задачу - защиту страны и союзников. Резерв является важной частью повышения боеспособности, мобилизации и устойчивости немецких вооруженных сил. Новая стратегия резерва направлена на значительное увеличение его численности и более тесную интеграцию в состав войск. Резерв рассматривается как неотъемлемая часть вооруженных сил. От задач охраны и обеспечения безопасности до участия в боевых действиях - резерв призван усилить регулярные войска во всех областях.",
    "Ответь одним коротким предложением: зачем нужен reranker в RAG?",
    "Ответь одним коротким предложением: чем embedding отличается от LLM?",
    "Ответь длинным предложением про космическую вселенную!"
]


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("benchmark.log"),
    ],
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

logger = logging.getLogger("benchmark")


# ===================== DATA =====================

@dataclass
class BenchResult:
    client: str
    duration: float
    ttft: float | None
    gen_time: float | None
    tokens: int
    tok_sec: float


# ===================== UTILS =====================

def count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def calc_metrics(duration, ttft, text):
    tokens = count_tokens(text)

    if ttft is not None:
        gen_time = max(duration - ttft, 1e-6)
        tok_sec = tokens / gen_time
    else:
        gen_time = None
        tok_sec = 0

    return tokens, gen_time, tok_sec


# ===================== CLIENTS =====================

def run_http(prompt):
    start = time.time()
    first_token = None
    text = ""

    r = requests.post(
        settings.llm_url,
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "options": {"temperature": TEMPERATURE},
        },
        timeout=settings.llm_timeout,
        stream=True,
    )

    r.raise_for_status()

    for line in r.iter_lines():
        if not line:
            continue

        if line.startswith(b"data: "):
            line = line[6:]

        if line == b"[DONE]":
            break

        try:
            data = json.loads(line)
            delta = data["choices"][0]["delta"].get("content", "")
        except:
            continue

        if not delta:
            continue

        if first_token is None:
            first_token = time.time()

        text += delta

    duration = time.time() - start
    ttft = (first_token - start) if first_token else None

    tokens, gen_time, tok_sec = calc_metrics(duration, ttft, text)

    return BenchResult("HTTP", duration, ttft, gen_time, tokens, tok_sec)


def run_openai(prompt):
    client = OpenAI(
        base_url=settings.llm_openai_url,
        api_key=settings.llm_openai_api_key,
    )

    start = time.time()
    first_token = None
    text = ""

    stream = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE,
        stream=True,
    )

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta.content or ""

        if not delta:
            continue

        if first_token is None:
            first_token = time.time()

        text += delta

    duration = time.time() - start
    ttft = (first_token - start) if first_token else None

    tokens, gen_time, tok_sec = calc_metrics(duration, ttft, text)

    return BenchResult("OPENAI_SDK", duration, ttft, gen_time, tokens, tok_sec)


def run_native(prompt):
    start = time.time()
    first_token = None
    text = ""

    r = requests.post(
        settings.ollama_url,
        json={
            "model": MODEL,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=settings.llm_timeout,
        stream=True,
    )

    r.raise_for_status()

    for line in r.iter_lines():
        if not line:
            continue

        try:
            data = json.loads(line)
            delta = data.get("message", {}).get("content", "")
        except:
            continue

        if not delta:
            continue

        if first_token is None:
            first_token = time.time()

        text += delta

    duration = time.time() - start
    ttft = (first_token - start) if first_token else None

    tokens, gen_time, tok_sec = calc_metrics(duration, ttft, text)

    return BenchResult("OLLAMA_NATIVE", duration, ttft, gen_time, tokens, tok_sec)


# ===================== SUMMARY =====================

def print_summary(results: dict):
    def avg(xs):
        return sum(xs) / len(xs) if xs else 0

    rows = []

    for name, items in results.items():
        rows.append({
            "CLIENT": name,
            "AVG DUR": f"{avg([x.duration for x in items]):.2f}",
            "AVG TTFT": f"{avg([x.ttft for x in items if x.ttft is not None]):.2f}",
            "AVG GEN": f"{avg([x.gen_time for x in items if x.gen_time is not None]):.2f}",
            "AVG TOK/S": f"{avg([x.tok_sec for x in items]):.1f}",
            "TOTAL TOK": str(sum(x.tokens for x in items)),
        })

    headers = list(rows[0].keys())

    col_widths = {
        h: max(len(h), max(len(r[h]) for r in rows))
        for h in headers
    }

    def format_row(row):
        return " | ".join(
            row[h].ljust(col_widths[h]) for h in headers
        )

    separator = "-+-".join("-" * col_widths[h] for h in headers)

    logger.info("\n=== SUMMARY TABLE ===")
    logger.info(format_row({h: h for h in headers}))
    logger.info(separator)

    for row in rows:
        logger.info(format_row(row))


# ===================== MAIN =====================

def main():
    results = {
        "HTTP": [],
        "OPENAI_SDK": [],
        "OLLAMA_NATIVE": [],
    }

    runners = {
        "HTTP": run_http,
        "OPENAI_SDK": run_openai,
        "OLLAMA_NATIVE": run_native,
    }

    logger.info("\n=== BENCHMARK ===")
    logger.info(f"MODEL: {MODEL}")
    logger.info(f"TEMPERATURE: {TEMPERATURE}")
    logger.info(f"PROMPTS: {len(PROMPTS)}\n")

    for prompt in PROMPTS:
        logger.info(f"\nPROMPT: {prompt}")

        for name, fn in runners.items():
            res = fn(prompt)
            results[name].append(res)

            logger.info(
                f"{name}: "
                f"dur={res.duration:.2f}s "
                f"ttft={res.ttft:.2f}s "
                f"tok/s={res.tok_sec:.1f} "
                f"tokens={res.tokens}"
            )

    print_summary(results)


if __name__ == "__main__":
    main()