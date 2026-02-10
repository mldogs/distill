"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import type { User, TelegramAuthData } from "@/types";

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (data: TelegramAuthData) => Promise<void>;
  devLogin: (username?: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Check auth on mount
  useEffect(() => {
    checkAuth();
  }, []);

  async function checkAuth() {
    const token = api.getToken();
    if (!token) {
      setLoading(false);
      return;
    }

    try {
      const userData = await api.getMe();
      setUser(userData);
    } catch {
      api.logout();
    } finally {
      setLoading(false);
    }
  }

  const login = useCallback(async (data: TelegramAuthData) => {
    try {
      const response = await api.authTelegram(data);
      setUser(response.user);
    } catch (error) {
      console.error("Telegram login failed:", error);
      throw error;
    }
  }, []);

  const devLogin = useCallback(async (username: string = "test_user") => {
    try {
      const response = await api.devLogin(username);
      setUser(response.user);
    } catch (error) {
      console.error("Dev login failed:", error);
      throw error;
    }
  }, []);

  const logout = useCallback(() => {
    api.logout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        devLogin,
        logout,
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
