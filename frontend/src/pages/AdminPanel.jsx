import { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const METABASE_EMBED_URL = import.meta.env.VITE_METABASE_EMBED_URL || "";

function getToken() {
  return localStorage.getItem("token") || "";
}

function getStoredUser() {
  try {
    const raw = localStorage.getItem("user");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function badgeClass(status) {
  if (status === "confirmed") return "bg-emerald-100 text-emerald-700";
  if (status === "pending") return "bg-amber-100 text-amber-700";
  if (status === "cancelled") return "bg-rose-100 text-rose-700";
  if (status === "rented") return "bg-indigo-100 text-indigo-700";
  if (status === "available") return "bg-emerald-100 text-emerald-700";
  return "bg-slate-100 text-slate-700";
}

export default function AdminPanel({ currentUser }) {
  const [bookings, setBookings] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [error, setError] = useState("");

  const user = currentUser || getStoredUser();
  const isAdmin = user?.role === "admin";

  useEffect(() => {
    if (!isAdmin) return;
    const loadData = async () => {
      setError("");
      try {
        const [bookingsRes, vehiclesRes] = await Promise.all([
          axios.get(`${API_BASE}/bookings`, { headers: authHeaders() }),
          axios.get(`${API_BASE}/vehicles`, { headers: authHeaders() }),
        ]);
        setBookings(Array.isArray(bookingsRes.data) ? bookingsRes.data : []);
        setVehicles(Array.isArray(vehiclesRes.data) ? vehiclesRes.data : []);
      } catch {
        setError("Failed to load admin data.");
      }
    };
    loadData();
  }, [isAdmin]);

  const fleetByStatus = useMemo(() => {
    return vehicles.reduce((acc, vehicle) => {
      const key = vehicle.status || "unknown";
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
  }, [vehicles]);

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <div className="rounded-2xl bg-rose-50 p-6 text-rose-700 ring-1 ring-rose-200">
          You do not have access to the admin panel.
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="text-3xl font-bold text-slate-900">Admin Panel</h1>
      {error && <p className="mt-4 rounded-xl bg-red-100 p-3 text-red-700">{error}</p>}

      <section className="mt-8">
        <h2 className="text-xl font-semibold text-slate-900">All Bookings</h2>
        <div className="mt-4 overflow-x-auto rounded-2xl bg-white shadow ring-1 ring-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-3 font-medium">Booking ID</th>
                <th className="px-4 py-3 font-medium">Customer</th>
                <th className="px-4 py-3 font-medium">Vehicle</th>
                <th className="px-4 py-3 font-medium">Dates</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {bookings.map((booking) => (
                <tr key={booking.id} className="border-t border-slate-100">
                  <td className="px-4 py-3">{booking.id}</td>
                  <td className="px-4 py-3">{booking.customer_id}</td>
                  <td className="px-4 py-3">{booking.vehicle_id}</td>
                  <td className="px-4 py-3">
                    {new Date(booking.pickup_date).toLocaleDateString()} -{" "}
                    {new Date(booking.return_date).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-1 text-xs font-medium ${badgeClass(booking.status)}`}>
                      {booking.status}
                    </span>
                  </td>
                </tr>
              ))}
              {bookings.length === 0 && (
                <tr>
                  <td className="px-4 py-4 text-slate-500" colSpan={5}>
                    No bookings found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-xl font-semibold text-slate-900">Fleet Status Grid</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {Object.entries(fleetByStatus).map(([status, count]) => (
            <div key={status} className="rounded-xl bg-white p-5 shadow ring-1 ring-slate-200">
              <p className="text-sm text-slate-500">{status}</p>
              <p className="mt-2 text-2xl font-bold text-indigo-600">{count}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-xl font-semibold text-slate-900">Analytics</h2>
        <div className="mt-4 overflow-hidden rounded-2xl bg-white shadow ring-1 ring-slate-200">
          {METABASE_EMBED_URL ? (
            <iframe
              title="Metabase Analytics"
              src={METABASE_EMBED_URL}
              className="h-[560px] w-full"
              frameBorder="0"
            />
          ) : (
            <div className="p-6 text-sm text-slate-500">Set REACT_APP_METABASE_EMBED_URL to embed dashboard.</div>
          )}
        </div>
      </section>
    </div>
  );
}
