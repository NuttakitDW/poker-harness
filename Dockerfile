# Discord bot (make bot) for Railway. Only the bot's runtime is shipped, not the voice stack.
# libraqm0 gives Pillow complex text layout so Thai vowels and tone marks stack correctly.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-tlwg-mono-ttf libraqm0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY deploy/requirements-bot.txt deploy/
RUN pip install --no-cache-dir -r deploy/requirements-bot.txt

COPY scripts/ scripts/
COPY pushfold/ pushfold/
COPY harnesses/ harnesses/
# Prebuilt caches (tmp/ is gitignored; building them takes ~35 min)
COPY tmp/equity.sqlite tmp/equity-tables.npz tmp/pushfold-e2.npz tmp/pushfold-e3.npz tmp/

# Railway shows the host's 48 CPUs but the plan allows 8; without a cap OpenBLAS starts
# 48 threads and one solve takes 70s instead of 3.5s.
ENV CHART_FONT=/usr/share/fonts/truetype/tlwg/TlwgMono.ttf \
    PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=8

CMD ["python", "scripts/discord_bot/bot.py"]
