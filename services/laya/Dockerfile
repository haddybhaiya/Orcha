FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 USE_TF=0 \
    HF_HUB_DISABLE_XET=1 HF_HOME=/opt/hf LAYA_MODEL_DIR=/opt/laya-model \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 PORT=8080
WORKDIR /app
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.9.1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home app && mkdir -p /opt/hf /opt/laya-model \
    && chown app:app /opt/hf /opt/laya-model /app
COPY --chown=app:app prepare_model.py service.py ./
COPY --chown=app:app NOTICE.md ./
USER app
RUN python prepare_model.py
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["python", "service.py"]
