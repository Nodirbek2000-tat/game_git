# Harakat o‘yinlari — backend (Django)

Django + DRF API. Lokal ishga tushirish:

```bash
python -m venv venv
venv/Scripts/pip install -r requirements.txt   # Linux: venv/bin/pip
cp .env.example .env      # lokalda DJANGO_DEBUG=true qiling
python manage.py migrate
python manage.py runserver
```

Serverga joylash: [DEPLOY.md](DEPLOY.md). Frontend: `game_next_git` repo.
