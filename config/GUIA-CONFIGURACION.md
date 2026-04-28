# Guía de configuración (`pr-revisor`)

## 1) Archivos clave

- `config/repos.yaml` → repositorios que atiende el servicio.
- `config/service.env.example` → plantilla de variables de entorno.
- `.env.local` → variables reales en tu máquina (no versionar secretos).

---

## 2) Estructura mínima de `repos.yaml`

```yaml
defaults:
  prompt: >-
    Revisa el PR y responde solo con JSON (status, summary, review_body, findings).
  include_paths: []
  exclude_paths:
    - .git/
    - node_modules/
    - dist/
  config_path: .pr-reviewer.yml
  requirements_file: requerimientos.md
  opencode_command: [opencode.cmd, run]

repos:
  - workspace: mi-workspace
    slug: mi-repo
    clone_url: git@bitbucket.org:mi-workspace/mi-repo.git
    human_workspace_root: C:/src/mi-repo
    bot_workspace_root: C:/pr-revisor-bot/mi-repo
    webhook_secret_env: BB_MI_REPO_WEBHOOK_SECRET
    bitbucket_token_env: BB_MI_REPO_API_TOKEN
```

---

## 3) Significado de cada campo

### `defaults`
- `prompt`: instrucciones base para el modelo.
- `include_paths` / `exclude_paths`: alcance de revisión.
- `config_path`: archivo opcional por repo (vive en repo objetivo).
- `requirements_file`: markdown de requisitos (vive en repo objetivo).
- `opencode_command`: comando ejecutado por el servicio para revisar.

### `repos[]`
- `workspace`: workspace de Bitbucket Cloud.
- `slug`: slug del repositorio (URL-friendly).
- `clone_url`: URL de clonación usada por el bot.
- `human_workspace_root`: clon para uso manual (SSH + opencode).
- `bot_workspace_root`: mirror/workspaces del bot para PRs.
- `webhook_secret_env`: nombre de variable con secreto del webhook.
- `bitbucket_token_env`: nombre de variable con token API Bitbucket.

---

## 4) Ejemplo con múltiples repos

```yaml
defaults:
  prompt: Revisa el PR y devuelve JSON conciso.
  include_paths: []
  exclude_paths: []
  config_path: .pr-reviewer.yml
  requirements_file: requerimientos.md
  opencode_command: [opencode.cmd, run]

repos:
  - workspace: equipo-a
    slug: api-clientes
    clone_url: git@bitbucket.org:equipo-a/api-clientes.git
    human_workspace_root: C:/src/api-clientes
    bot_workspace_root: C:/pr-revisor-bot/api-clientes
    webhook_secret_env: BB_API_CLIENTES_WEBHOOK_SECRET
    bitbucket_token_env: BB_API_CLIENTES_API_TOKEN

  - workspace: equipo-a
    slug: web-admin
    clone_url: git@bitbucket.org:equipo-a/web-admin.git
    human_workspace_root: C:/src/web-admin
    bot_workspace_root: C:/pr-revisor-bot/web-admin
    webhook_secret_env: BB_WEB_ADMIN_WEBHOOK_SECRET
    bitbucket_token_env: BB_WEB_ADMIN_API_TOKEN
    review:
      prompt: >-
        Revisa con foco en seguridad frontend, regresiones UI y cobertura de tests.
```

---

## 5) Variables de entorno (ejemplo)

```env
PR_REVISOR_HOST=127.0.0.1
PR_REVISOR_PORT=8001
PR_REVISOR_REPOS_CONFIG=config/repos.yaml

BB_API_CLIENTES_WEBHOOK_SECRET=...
BB_API_CLIENTES_API_TOKEN=...

BB_WEB_ADMIN_WEBHOOK_SECRET=...
BB_WEB_ADMIN_API_TOKEN=...
```

---

## 6) Dónde viven `.pr-reviewer.yml` y `requerimientos.md`

Ambos viven en el **repositorio objetivo** (el que se revisa), no en este repo del servicio.

- `<repo-objetivo>/.pr-reviewer.yml`
- `<repo-objetivo>/requerimientos.md`

El servicio los lee desde el workspace preparado del PR.

---

## 7) Errores típicos

- `404 Not Found` en webhook → URL sin `/webhooks/bitbucket` (aunque hay fallback en `/`).
- `401 Invalid webhook signature` → secret en Bitbucket distinto al de env var.
- `Repository not registered` → `workspace/slug` no coincide con `repos.yaml`.
- `FileNotFoundError opencode` → usar `opencode.cmd` o revisar PATH.
