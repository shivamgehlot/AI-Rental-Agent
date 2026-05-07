import { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

function getToken() {
  return localStorage.getItem("token") || "";
}

function headers() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function Dashboard({ customerId }) {
  const [bookings, setBookings] = useState([]);
  const [customer, setCustomer] = useState(null);
  const [insuranceDocs, setInsuranceDocs] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const loadDashboard = async () => {
      if (!customerId) return;
      setError("");
      try {
        const [customerRes, bookingsRes] = await Promise.all([
          axios.get(`${API_BASE}/customers/${customerId}`, { headers: headers() }),
          axios.get(`${API_BASE}/customers/${customerId}/bookings`, { headers: headers() }),
        ]);
        setCustomer(customerRes.data);
        const bookingItems = Array.isArray(bookingsRes.data) ? bookingsRes.data : [];
        setBookings(bookingItems);

        try {
          const docsRes = await axios.get(`${API_BASE}/customers/${customerId}/insurance-documents`, {
            headers: headers(),
          });
          setInsuranceDocs(Array.isArray(docsRes.data) ? docsRes.data : []);
        } catch {
          setInsuranceDocs([]);
        }
      } catch {
        setError("Unable to load dashboard data.");
      }
    };
    loadDashboard();
  }, [customerId]);

  const activeBookings = useMemo(
    () => bookings.filter((booking) => booking.status === "pending" || booking.status === "confirmed"),
    [bookings],
  );
  const pastBookings = useMemo(
    () => bookings.filter((booking) => booking.status === "cancelled" || booking.status === "completed"),
    [bookings],
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="text-3xl font-bold text-slate-900">Customer Dashboard</h1>
      {error && <p className="mt-4 rounded-xl bg-red-100 p-3 text-red-700">{error}</p>}

      <section className="mt-6 grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl bg-white p-5 shadow ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">Customer</p>
          <p className="mt-2 text-lg font-semibold">{customer?.full_name || "—"}</p>
          <p className="text-sm text-slate-600">{customer?.email || ""}</p>
        </div>
        <div className="rounded-2xl bg-white p-5 shadow ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">Loyalty Points</p>
          <p className="mt-2 text-2xl font-bold text-indigo-600">{customer?.loyalty_points ?? 0}</p>
        </div>
        <div className="rounded-2xl bg-white p-5 shadow ring-1 ring-slate-200">
          <p className="text-sm text-slate-500">Insurance Documents</p>
          <p className="mt-2 text-2xl font-bold text-emerald-600">{insuranceDocs.length}</p>
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-xl font-semibold text-slate-900">Active Bookings</h2>
        <div className="mt-3 space-y-3">
          {activeBookings.map((booking) => (
            <div key={booking.id} className="rounded-xl bg-white p-4 shadow ring-1 ring-slate-200">
              <p className="font-medium text-slate-900">Booking #{booking.id}</p>
              <p className="text-sm text-slate-600">
                {new Date(booking.pickup_date).toLocaleDateString()} -{" "}
                {new Date(booking.return_date).toLocaleDateString()}
              </p>
              <p className="text-sm text-indigo-600">${booking.total_price}</p>
            </div>
          ))}
          {activeBookings.length === 0 && <p className="text-sm text-slate-500">No active bookings.</p>}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-xl font-semibold text-slate-900">Past Bookings</h2>
        <div className="mt-3 space-y-3">
          {pastBookings.map((booking) => (
            <div key={booking.id} className="rounded-xl bg-white p-4 shadow ring-1 ring-slate-200">
              <p className="font-medium text-slate-900">Booking #{booking.id}</p>
              <p className="text-sm text-slate-600">
                {new Date(booking.pickup_date).toLocaleDateString()} -{" "}
                {new Date(booking.return_date).toLocaleDateString()}
              </p>
              <p className="text-sm text-slate-500">Status: {booking.status}</p>
            </div>
          ))}
          {pastBookings.length === 0 && <p className="text-sm text-slate-500">No past bookings.</p>}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-xl font-semibold text-slate-900">Insurance Documents</h2>
        <div className="mt-3 space-y-2">
          {insuranceDocs.map((doc) => (
            <a
              key={doc.id}
              href={doc.file_url}
              target="_blank"
              rel="noreferrer"
              className="block rounded-xl bg-white p-4 text-sm text-indigo-600 shadow ring-1 ring-slate-200 hover:underline"
            >
              {doc.file_name}
            </a>
          ))}
          {insuranceDocs.length === 0 && (
            <p className="text-sm text-slate-500">No insurance documents found.</p>
          )}
        </div>
      </section>
    </div>
  );
}
