CREATE TABLE IF NOT EXISTS USERS (
    username VARCHAR(255) PRIMARY KEY,
    password TEXT NOT NULL,
    credits INTEGER NOT NULL,
    is_admin BOOLEAN NOT NULL,
    total_requests INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS SEARCH_HISTORY (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    bounds JSON NOT NULL,
    search_type VARCHAR(50),
    subarea_step FLOAT,
    subarea_radius FLOAT,
    total_requests INTEGER,
    map_html TEXT,
    center_lat FLOAT,
    center_lon FLOAT,
    zoom INTEGER,
    timestamp DATETIME,
    FOREIGN KEY (user_id) REFERENCES USERS(username)
);

CREATE TABLE IF NOT EXISTS PHARMACIES (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    UNIQUE KEY unique_pharmacy (name, latitude, longitude)
);

CREATE TABLE IF NOT EXISTS SEARCH_PHARMACIES (
    search_id INTEGER,
    pharmacy_id INTEGER,
    PRIMARY KEY (search_id, pharmacy_id),
    FOREIGN KEY (search_id) REFERENCES SEARCH_HISTORY(id),
    FOREIGN KEY (pharmacy_id) REFERENCES PHARMACIES(id)
);

CREATE TABLE IF NOT EXISTS ACTIVE_IPS (
    ip_address VARCHAR(45) PRIMARY KEY,
    added_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL
);

CREATE INDEX idx_search_history_user_id_name ON SEARCH_HISTORY(user_id, name);
CREATE INDEX idx_active_ips_expires_at ON ACTIVE_IPS(expires_at);