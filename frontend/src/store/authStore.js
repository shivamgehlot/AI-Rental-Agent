import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const useAuthStore = create(
  persist(
    (set) => ({
      user: null,
      token: null,
      refreshToken: null,
      login: async (email, password) => {
        const { data } = await axios.post(`${API_BASE}/auth/login`, { email, password });
        set({
          token: data.access_token,
          refreshToken: data.refresh_token,
        });

        try {
          const payload = JSON.parse(atob(data.access_token.split(".")[1]));
          set({
            user: payload.sub
              ? {
                  id: payload.sub,
                  email,
                  role: payload.role || "customer",
                }
              : null,
          });
        } catch {
          set({ user: { email, role: "customer" } });
        }
      },
      logout: () => set({ user: null, token: null, refreshToken: null }),
    }),
    {
      name: "rideswift-auth",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        refreshToken: state.refreshToken,
      }),
    },
  ),
);

