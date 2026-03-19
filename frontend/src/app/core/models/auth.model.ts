export interface AuthUserSettings {
    language: string;
    timezone: string;
    ui_prefs?: Record<string, any>;
}

export interface AuthUser {
    uuid: string;
    name: string;
    email?: string | null;
    login?: string | null;
    role: string;
    trust_level: number;
    is_active: boolean;
    created_at?: string | null;
    last_login_at?: string | null;
    settings?: AuthUserSettings;
}

export interface AuthTokenResponse {
    token_type: string;
    access_token: string;
    refresh_token: string;
    access_expires_at?: string;
    refresh_expires_at?: string;
    session_id?: string;
    user: AuthUser;
}

export interface AuthLoginRequest {
    identity: string;
    password: string;
}

export interface AuthRegisterRequest {
    email: string;
    password: string;
    login?: string;
    name?: string;
    role?: string;
    language?: string;
    timezone?: string;
}

export interface AuthBootstrapState {
    has_owner: boolean;
    requires_setup: boolean;
    auth_users_count: number;
    first_registration_role: 'owner' | 'user';
    allow_anonymous: boolean;
}
