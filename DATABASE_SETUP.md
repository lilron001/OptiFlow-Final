-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

--------------------------------------------------
-- USERS
--------------------------------------------------

DROP TABLE IF EXISTS users CASCADE;

CREATE TABLE users (
    user_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT CHECK (role IN ('admin', 'operator'))
         NOT NULL DEFAULT 'operator',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- SIMPLE DEV RLS (FULL ACCESS)
CREATE POLICY "Users full access (dev)"
ON users
FOR ALL
USING (true)
WITH CHECK (true);

INSERT INTO users (username, email, password_hash, role)
VALUES (
    'admin',
    'admin@optiflow.local',
    '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9',
    'admin'
);

--------------------------------------------------
-- VEHICLES
--------------------------------------------------

DROP TABLE IF EXISTS vehicles CASCADE;

CREATE TABLE vehicles (
    vehicle_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    vehicle_type TEXT NOT NULL,
    lane INTEGER NOT NULL,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    detected_by TEXT CHECK (detected_by IN ('YOLO', 'MANUAL')) DEFAULT 'YOLO'
);

CREATE INDEX idx_vehicles_detected_at ON vehicles(detected_at);

ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Vehicles full access (dev)"
ON vehicles
FOR ALL
USING (true)
WITH CHECK (true);

--------------------------------------------------
-- VIOLATIONS
--------------------------------------------------

DROP TABLE IF EXISTS violations CASCADE;

CREATE TABLE violations (
    violation_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    vehicle_id UUID REFERENCES vehicles(vehicle_id) ON DELETE SET NULL,
    violation_type TEXT NOT NULL,
    lane INTEGER NOT NULL,
    source TEXT CHECK (source IN ('SYSTEM', 'MANUAL')) NOT NULL,
    reported_by UUID REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_violations_created_at ON violations(created_at);

ALTER TABLE violations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Violations full access (dev)"
ON violations
FOR ALL
USING (true)
WITH CHECK (true);

--------------------------------------------------
-- ACCIDENTS
--------------------------------------------------

DROP TABLE IF EXISTS accidents CASCADE;

CREATE TABLE accidents (
    accident_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    violation_id UUID REFERENCES violations(violation_id) ON DELETE SET NULL,
    lane INTEGER NOT NULL,
    description TEXT,
    severity TEXT CHECK (severity IN ('Minor', 'Moderate', 'Severe')) NOT NULL,
    detection_type TEXT CHECK (detection_type IN ('SYSTEM', 'MANUAL')) NOT NULL,
    reported_by UUID REFERENCES users(user_id) ON DELETE SET NULL,
    validated_by UUID REFERENCES users(user_id) ON DELETE SET NULL,
    status TEXT CHECK (status IN ('pending', 'validated', 'false_alarm'))
           DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE INDEX idx_accidents_status ON accidents(status);

ALTER TABLE accidents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Accidents full access (dev)"
ON accidents
FOR ALL
USING (true)
WITH CHECK (true);

--------------------------------------------------
-- REPORTS
--------------------------------------------------
DROP TABLE IF EXISTS reports CASCADE;

CREATE TABLE reports (
    report_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT CHECK(priority IN ('Low', 'Medium', 'High')) NOT NULL DEFAULT 'Medium',
    status TEXT CHECK(status IN ('Open', 'In Progress', 'Resolved', 'Closed')) NOT NULL DEFAULT 'Open',
    author_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    author_name TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Enable access for authenticated users
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;

-- Create open policies (Application handles validation)
CREATE POLICY "Enable public read access" ON reports
    FOR SELECT USING (true);

CREATE POLICY "Enable public insert access" ON reports
    FOR INSERT WITH CHECK (true);
    
CREATE POLICY "Enable public update access" ON reports
    FOR UPDATE USING (true);

--------------------------------------------------
-- EMERGENCY EVENTS
--------------------------------------------------

DROP TABLE IF EXISTS emergency_events CASCADE;

CREATE TABLE emergency_events (
    event_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    vehicle_type TEXT NOT NULL,
    lane INTEGER NOT NULL,
    action_taken TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

ALTER TABLE emergency_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Emergency events full access (dev)"
ON emergency_events
FOR ALL
USING (true)
WITH CHECK (true);

--------------------------------------------------
-- SYSTEM LOGS
--------------------------------------------------

DROP TABLE IF EXISTS system_logs CASCADE;

CREATE TABLE system_logs (
    log_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    event_type TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

ALTER TABLE system_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "System logs full access (dev)"
ON system_logs
FOR ALL
USING (true)
WITH CHECK (true);
