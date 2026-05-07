import { create } from "zustand";

const INVENTORY_WS_URL = "ws://backend/ws/inventory";

function mergeVehicleUpdate(vehicles, update) {
  const vehicleId = update.vehicle_id || update.id;
  if (!vehicleId) return vehicles;

  let found = false;
  const next = vehicles.map((vehicle) => {
    if (vehicle.id === vehicleId) {
      found = true;
      return { ...vehicle, ...update };
    }
    return vehicle;
  });

  if (!found) next.unshift({ id: vehicleId, ...update });
  return next;
}

export const useInventoryStore = create((set, get) => ({
  vehicles: [],
  socket: null,
  isConnected: false,
  reconnectTimer: null,

  setVehicles: (vehicles) => set({ vehicles: Array.isArray(vehicles) ? vehicles : [] }),

  connect: () => {
    const existing = get().socket;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const socket = new WebSocket(INVENTORY_WS_URL);

    socket.onopen = () => {
      const timer = get().reconnectTimer;
      if (timer) {
        clearTimeout(timer);
      }
      set({ isConnected: true, reconnectTimer: null });
    };

    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        set((state) => ({ vehicles: mergeVehicleUpdate(state.vehicles, parsed) }));
      } catch {
        set((state) => ({
          vehicles: mergeVehicleUpdate(state.vehicles, {
            vehicle_id: String(event.data),
          }),
        }));
      }
    };

    socket.onclose = () => {
      set({ isConnected: false, socket: null });
      const timer = setTimeout(() => get().connect(), 2000);
      set({ reconnectTimer: timer });
    };

    socket.onerror = () => {
      socket.close();
    };

    set({ socket });
  },

  disconnect: () => {
    const socket = get().socket;
    const timer = get().reconnectTimer;
    if (timer) clearTimeout(timer);
    if (socket) socket.close();
    set({ socket: null, isConnected: false, reconnectTimer: null });
  },
}));

