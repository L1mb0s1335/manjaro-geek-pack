# manjaro-geek-pack

Минималистичный Manjaro/Arch-themed десктоп: живой дашборд системной статистики прямо в обоях KDE Plasma + набор аватарок/обоев в том же стиле.

## Что внутри

- **`conky-dash/`** — генератор дашборда.
  - `gen.py` — Python-скрипт, периодически рисует `dash.png` со статистикой системы (CPU/RAM/диск и т.п.) в `/run/user/<uid>/conky-dash/dash.png`.
  - `conky-dash.service` — systemd user-юнит, держит `gen.py` постоянно запущенным.
- **`plasma-wallpaper-plugin/`** — кастомный плагин обоев Plasma `org.susu.dashboard`. Берёт обычную картинку как фон и рисует поверх неё `dash.png` из `conky-dash` в углу экрана.
  - `metadata.json`, `contents/ui/main.qml`, `contents/ui/config.qml`, `contents/config/main.xml`
- **`wallpapers-avatars/`** — сгенерированные ИИ картинки в стиле Manjaro/Arch minimalism:
  - `avatar-manjaro-leaf.png`, `avatar-tux.png` — квадратные аватарки (1024×1024)
  - `wallpaper-desktop.png`, `wallpaper-lockscreen.png` — широкие обои (1344×752, 16:9)

## Установка (KDE Plasma, Manjaro/Arch)

```bash
# 1. генератор дашборда
mkdir -p ~/.local/share/conky-dash
cp conky-dash/gen.py ~/.local/share/conky-dash/
mkdir -p ~/.config/systemd/user
cp conky-dash/conky-dash.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now conky-dash.service

# 2. плагин обоев Plasma
mkdir -p ~/.local/share/plasma/wallpapers/org.susu.dashboard/contents/{ui,config}
cp plasma-wallpaper-plugin/metadata.json ~/.local/share/plasma/wallpapers/org.susu.dashboard/
cp plasma-wallpaper-plugin/ui/*.qml ~/.local/share/plasma/wallpapers/org.susu.dashboard/contents/ui/
cp plasma-wallpaper-plugin/config/main.xml ~/.local/share/plasma/wallpapers/org.susu.dashboard/contents/config/
```

Затем в настройках рабочего стола (правый клик на десктопе → «Настроить рабочий стол») выбрать тип обоев **Dashboard** (или как он там называется в списке), указать картинку фона и путь к `dash.png` (`/run/user/<uid>/conky-dash/dash.png`).

## Картинки

PNG из `wallpapers-avatars/` — обычные файлы, кладите как:
- аватар — Steam, GitHub, Discord и т.п. (квадратные)
- обои — рабочий стол / экран блокировки через System Settings → Wallpaper / Lock Screen

Сгенерированы нейросетью (GPT Image) под запрос «Manjaro/Arch минимализм».

## Лицензия

Личный конфиг, используйте и переделывайте как хочется.
