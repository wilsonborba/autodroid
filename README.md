# autodroid

Android automation worker com fila persistente, `CLI`, `API`, adapters por aplicativo e mapper local de UI Android.

## Sprint 1

A Sprint 1 entrega:
- `1` Android Worker
- fila persistente com `SQLite + SQLAlchemy + Alembic`
- dispatcher serial com prioridade, `run_after`, `cron_expression` e janela de execução
- `CLI` para jobs e worker
- `API` com `FastAPI`
- adapter inicial do LinkedIn com job `linkedin.extract_profile_basic`
- OCR com `PaddleOCR` apenas como fallback

## Sprint 1.1

A Sprint 1.1 entrega o `UI Mapper` local:
- persistência local do mapper em SQLite
- exploração por níveis `light`, `medium` e `deep`
- fingerprint de telas e mitigação básica de loops
- guard rails de `dangerous actions` por padrão
- override explícito para desabilitar o bloqueio de ações perigosas
- `CLI` e `API` para operações principais do mapper
- export local estruturado por sessão

## Arquitetura

```text
lib/
├── core/
├── dal/
│   ├── local/
│   └── remote/
├── domain/
│   ├── adapters/
│   ├── models/
│   └── services/
└── presentation/
    ├── api/
    └── cli/
```

## Requisitos

- Python `3.11+`
- `adb` disponível no `PATH`
- Android Worker acessível em `ANDROID_SERIAL`
- app alvo instalado no Android virtual

## Setup local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
autodroid db upgrade
```

## Variáveis principais

- `AUTODROID_DATABASE_URL` — padrão `sqlite:///./var/autodroid.db`
- `AUTODROID_WORKER_NAME` — padrão `main`
- `AUTODROID_TIMEZONE` — padrão `UTC`
- `ANDROID_SERIAL` — padrão `127.0.0.1:5555`
- `LINKEDIN_PACKAGE_NAME` — padrão `com.linkedin.android`
- `AUTODROID_OUTPUT_DIR` — padrão `output`

## CLI de jobs/worker

Criar job do LinkedIn:

```bash
autodroid jobs create linkedin.extract_profile_basic linkedin --payload '{"scrolls": 2}'
```

Executar uma iteração do dispatcher:

```bash
autodroid worker run --iterations 1
```

## API base

Subir API local:

```bash
autodroid serve-api --host 127.0.0.1 --port 8000
```

Rotas iniciais:
- `GET /health`
- `POST /jobs`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `POST /jobs/{job_id}/cancel`
- `POST /jobs/{job_id}/reprioritize`
- `GET /workers/main`

## UI Mapper

### Níveis

- `light`
  - execução em minutos
  - exploração rasa
  - poucas transições principais
- `medium`
  - execução em horas
  - exploração moderada com mais ações e scrolls
- `deep`
  - exploração extensiva
  - pode levar muitas horas ou mais, dependendo do app e dos limites

### Segurança

- ações perigosas são puladas por padrão
- exemplos: `delete`, `logout`, `send`, `post`, `purchase`, `submit`
- a proteção pode ser desabilitada explicitamente quando necessário

### CLI do mapper

Rodar mapper:

```bash
autodroid mapper run com.linkedin.android --mode light
```

Listar sessões:

```bash
autodroid mapper sessions --as-json
```

Mostrar sessão:

```bash
autodroid mapper show 1 --as-json
```

Exportar sessão:

```bash
autodroid mapper export 1
```

### API do mapper

- `POST /mapper/run`
- `GET /mapper/sessions`
- `GET /mapper/sessions/{session_id}`
- `POST /mapper/sessions/{session_id}/export`

### Artefatos locais

O mapper gera dados potencialmente sensíveis e privados. Esses artefatos:
- ficam apenas localmente
- não devem subir para o Git
- podem conter estrutura de telas, textos visíveis e outros dados de navegação

Diretório padrão de export local:

```text
output/mappers/
```

## Política da Sprint 1

- toda execução começa de `HOME`
- o app alvo é sempre encerrado completamente antes de abrir
- não existe retomada de progresso no meio da task
- placeholders de resume/contexto ficam preparados apenas para evolução futura

## Changelog

Configuração de `git-cliff` disponível em `cliff.toml`.
