export type UserRole = "user" | "admin";

export interface AuthUser {
  id: string;
  role: UserRole;
  display_name: string | null;
  email: string | null;
  phone: string | null;
  wechat_bound: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}
