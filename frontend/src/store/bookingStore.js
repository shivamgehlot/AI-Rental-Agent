import { create } from "zustand";
import axios from "axios";
import { useAuthStore } from "./authStore";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

export const useBookingStore = create((set, get) => ({
  step: 1,
  currentBooking: {
    customer_id: null,
    vehicle_id: null,
    pickup_date: null,
    return_date: null,
    total_price: 0,
    notes: null,
  },
  setStep: (step) => set({ step }),
  setVehicle: (vehicle) =>
    set((state) => ({
      currentBooking: {
        ...state.currentBooking,
        vehicle_id: vehicle?.id || null,
        vehicle,
      },
      step: 2,
    })),
  setDates: (pickupDate, returnDate) =>
    set((state) => ({
      currentBooking: {
        ...state.currentBooking,
        pickup_date: pickupDate,
        return_date: returnDate,
      },
      step: 3,
    })),
  setCustomer: (customerId) =>
    set((state) => ({
      currentBooking: {
        ...state.currentBooking,
        customer_id: customerId,
      },
    })),
  setTotalPrice: (amount) =>
    set((state) => ({
      currentBooking: {
        ...state.currentBooking,
        total_price: amount,
      },
    })),
  confirmBooking: async () => {
    const booking = get().currentBooking;
    const token = useAuthStore.getState().token;
    const headers = token ? { Authorization: `Bearer ${token}` } : {};

    const payload = {
      customer_id: booking.customer_id,
      vehicle_id: booking.vehicle_id,
      pickup_date: booking.pickup_date,
      return_date: booking.return_date,
      total_price: booking.total_price,
      notes: booking.notes,
    };

    const { data } = await axios.post(`${API_BASE}/bookings`, payload, { headers });
    set({
      step: 1,
      currentBooking: {
        customer_id: booking.customer_id,
        vehicle_id: null,
        pickup_date: null,
        return_date: null,
        total_price: 0,
        notes: null,
      },
    });
    return data;
  },
}));

