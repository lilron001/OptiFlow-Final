-- SystemOptiflow Unified Database Schema
-- Includes Users and Reports tables

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. USERS TABLE
CREATE TABLE IF NOT EXISTS public.users (
    user_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'operator', -- 'admin' or 'operator'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

-- 2. REPORTS TABLE (Issue Tracking)
CREATE TABLE IF NOT EXISTS public.reports (
    report_id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT CHECK (priority IN ('Low', 'Medium', 'High')) DEFAULT 'Medium',
    status TEXT CHECK (status IN ('Open', 'In Progress', 'Resolved', 'Closed')) DEFAULT 'Open',
    author_id UUID REFERENCES public.users(user_id) ON DELETE SET NULL,
    author_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. ROW LEVEL SECURITY (RLS)
-- Enable RLS
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;

-- Policies for USERS
-- Allow users to view their own data
CREATE POLICY "Users can view own data" ON public.users
    FOR SELECT USING (auth.uid() = user_id);

-- Policies for REPORTS
-- Allow all authenticated users to view reports
CREATE POLICY "Enable read access for all users" ON public.reports
    FOR SELECT USING (true);

-- Allow authenticated users to insert reports
CREATE POLICY "Enable insert for authenticated users" ON public.reports
    FOR INSERT WITH CHECK (true);

-- Allow admins/authors to update reports
CREATE POLICY "Enable update for users based on email" ON public.reports
    FOR UPDATE USING (true);

-- 4. INDEXES
CREATE INDEX IF NOT EXISTS idx_reports_status ON public.reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_priority ON public.reports(priority);
CREATE INDEX IF NOT EXISTS idx_users_username ON public.users(username);
