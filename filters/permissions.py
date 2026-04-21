from __future__ import annotations


PERM_USERS = "users"
PERM_KEYS = "keys"
PERM_TARIFFS = "tariffs"
PERM_CLUSTERS = "clusters"
PERM_BROADCASTING = "broadcasting"
PERM_COUPONS = "coupons"
PERM_GIFTS = "gifts"
PERM_STATS = "stats"
PERM_ADS = "ads"
PERM_MODULES = "modules"
PERM_SETTINGS = "settings"
PERM_MANAGEMENT = "management"
PERM_ADMINS = "admins"
PERM_EMOJI = "emoji"


PERMISSION_LABELS: dict[str, str] = {
    PERM_USERS: "👤 Пользователи",
    PERM_KEYS: "🔑 Подписки",
    PERM_TARIFFS: "💸 Тарифы",
    PERM_CLUSTERS: "🖥️ Серверы",
    PERM_BROADCASTING: "📢 Рассылки",
    PERM_COUPONS: "🎟️ Купоны",
    PERM_GIFTS: "🎁 Подарки",
    PERM_STATS: "📊 Статистика",
    PERM_ADS: "📈 UTM / Аналитика",
    PERM_MODULES: "🧩 Модули",
    PERM_SETTINGS: "⚙️ Настройки",
    PERM_MANAGEMENT: "🤖 Управление ботом",
    PERM_ADMINS: "👑 Управление админами",
    PERM_EMOJI: "😀 Эмоджи",
}

ALL_PERMISSIONS: tuple[str, ...] = tuple(PERMISSION_LABELS.keys())


def normalize_permissions(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        if item in PERMISSION_LABELS and item not in seen:
            seen.add(item)
            result.append(item)
    return result
