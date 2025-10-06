-- Создание таблицы для отслеживания синхронизации
CREATE TABLE IF NOT EXISTS sync_history (
    service TEXT PRIMARY KEY,
    last_sync TEXT
);

-- Создание таблицы для хранения треков (маппинг между сервисами)
CREATE TABLE IF NOT EXISTS tracks (
    yandex_id TEXT,
    spotify_id TEXT,
    artist TEXT,
    title TEXT,
    PRIMARY KEY (yandex_id, spotify_id)
);

-- Создание таблицы плейлистов
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    playlist_id TEXT NOT NULL,
    name TEXT,
    owner TEXT,
    UNIQUE(service, playlist_id)
);

-- Создание таблицы треков внутри плейлистов
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_pk INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    service TEXT NOT NULL,
    track_id TEXT NOT NULL,
    position INTEGER,
    added_at TEXT,
    PRIMARY KEY (playlist_pk, service, track_id)
);

-- Избранные альбомы
CREATE TABLE IF NOT EXISTS favorite_albums (
    service TEXT NOT NULL,
    album_id TEXT NOT NULL,
    name TEXT,
    artist TEXT,
    last_seen TEXT,
    PRIMARY KEY (service, album_id)
);

-- Избранные исполнители
CREATE TABLE IF NOT EXISTS favorite_artists (
    service TEXT NOT NULL,
    artist_id TEXT NOT NULL,
    name TEXT,
    last_seen TEXT,
    PRIMARY KEY (service, artist_id)
);

-- Соответствия избранных альбомов между сервисами
CREATE TABLE IF NOT EXISTS album_links (
    yandex_id TEXT PRIMARY KEY,
    spotify_id TEXT UNIQUE NOT NULL,
    normalized_key TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Соответствия избранных исполнителей между сервисами
CREATE TABLE IF NOT EXISTS artist_links (
    yandex_id TEXT PRIMARY KEY,
    spotify_id TEXT UNIQUE NOT NULL,
    normalized_key TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);