# Руководство по участию в проекте Spondex

Спасибо, что хотите внести вклад!

## 1. Форк и локальная настройка
```bash
git clone https://github.com/SergeyLavrentev/spondex.git
cd spondex
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## 2. Git remotes (если работаете через форк)
Обычно ваш форк — это `origin`. Если нужно получать апдейты из основного репо, добавьте его как `upstream`:
```bash
git remote add upstream https://github.com/SergeyLavrentev/spondex.git
git fetch upstream
```
Обновление вашей ветки `main`:
```bash
git checkout main
git fetch upstream
git rebase upstream/main   # или git merge upstream/main
```

## 3. Создание ветки и работа
```bash
git checkout -b feature/awesome-thing
# ... код ...
git add .
git commit -m "feat: add awesome thing"
git push -u origin feature/awesome-thing
```

## 4. Стиль коммитов (Conventional Commits)
Используем краткую структуру:
```
<type>: <кратко>

[опционально подробности]
```
Типы: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `chore`, `build`.
Примеры:
```
feat: add playlist cleanup utilities
fix: handle malformed Spotify cache JSON
```

## 5. Pull Request
1. Убедитесь, что ветка основана на актуальном `main`.
2. Прогоните линт/тесты (когда появятся тесты).
3. Создайте PR: base = `main`, compare = ваша фича.
4. В описании: цель, что сделано, есть ли побочные эффекты.

## 6. Синхронизация форка
```bash
git fetch upstream
git rebase upstream/main
git push origin main
```
Если конфликт при rebase:
```bash
git status               # смотрим конфликтующие файлы
# правим, затем
git add <file>
git rebase --continue
# отменить: git rebase --abort
```
Откат после неудачного rebase:
```bash
git reflog
git reset --hard <hash>
```

## 7. Alias (опционально)
```ini
[alias]
  up = !git fetch upstream && git rebase upstream/main
  sync = !git fetch upstream && git checkout main && git rebase upstream/main && git push origin main
  st = status -sb
  lg = log --oneline --graph --decorate --all
```

## 8. Стиль кода
- Python ≥ 3.9
- Следуем PEP8 (можно настроить black/ruff позже)
- Именование: явные названия функций/переменных
- Логика работы с API — оборачивать в функции/классы, не плодить скриптовый код в `main.py`

## 9. Предложения по улучшению
Если не уверены — создайте Issue перед реализацией крупной задачи.

## 10. Безопасность токенов
Не коммитьте `.env` и `.cache`. Они в `.gitignore` — не удаляйте это.

---
Если нужно добавить разделы (тестирование, релизы, CI) — создайте Issue или PR.
