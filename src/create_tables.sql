-- Создание таблицы для отслеживания синхронизации
CREATE TABLE IF NOT EXISTS sync_history (
    service VARCHAR(50) PRIMARY KEY,
    last_sync TIMESTAMP WITH TIME ZONE
);

-- Создание таблицы для хранения треков
CREATE TABLE IF NOT EXISTS tracks (
    yandex_id VARCHAR(50),
    spotify_id VARCHAR(50),
    artist VARCHAR(255),
    title VARCHAR(255),
    PRIMARY KEY (yandex_id, spotify_id)
);

-- Создание таблицы для ненайденных треков
CREATE TABLE IF NOT EXISTS undiscovered_tracks (
    id SERIAL PRIMARY KEY,
    service VARCHAR(50),
    artist VARCHAR(255),
    title VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
); 

-- Создание таблицы плейлистов
CREATE TABLE IF NOT EXISTS playlists (
    id SERIAL PRIMARY KEY,
    service VARCHAR(50) NOT NULL,
    playlist_id VARCHAR(100) NOT NULL,
    name VARCHAR(255),
    owner VARCHAR(255),
    last_synced TIMESTAMP WITH TIME ZONE,
    UNIQUE(service, playlist_id)
);

-- Создание таблицы треков внутри плейлистов
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_pk INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    service VARCHAR(50) NOT NULL,
    track_id VARCHAR(100) NOT NULL,
    position INTEGER,
    added_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (playlist_pk, service, track_id)
);

-- Избранные альбомы
CREATE TABLE IF NOT EXISTS favorite_albums (
    service VARCHAR(50) NOT NULL,
    album_id VARCHAR(100) NOT NULL,
    name VARCHAR(255),
    artist VARCHAR(255),
    last_seen TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (service, album_id)
);

-- Избранные исполнители
CREATE TABLE IF NOT EXISTS favorite_artists (
    service VARCHAR(50) NOT NULL,
    artist_id VARCHAR(100) NOT NULL,
    name VARCHAR(255),
    last_seen TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (service, artist_id)
);

-- Соответствия избранных альбомов между сервисами
CREATE TABLE IF NOT EXISTS album_links (
    yandex_id VARCHAR(100) PRIMARY KEY,
    spotify_id VARCHAR(100) UNIQUE NOT NULL,
    normalized_key VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Соответствия избранных исполнителей между сервисами
CREATE TABLE IF NOT EXISTS artist_links (
    yandex_id VARCHAR(100) PRIMARY KEY,
    spotify_id VARCHAR(100) UNIQUE NOT NULL,
    normalized_key VARCHAR(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);