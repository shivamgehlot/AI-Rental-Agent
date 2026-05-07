import { useMemo, useState } from "react";
import axios from "axios";
import { Toaster, toast } from "react-hot-toast";
import { useAuthStore } from "../store/authStore";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const VEHICLE_TYPES = ["sedan", "suv", "hatchback", "ev", "bike"];
const LOCATIONS = ["Airport", "City Center", "Railway Station", "Mall"];

function statusDotClass(status) {
  if (status === "available") return "bg-emerald-500";
  if (status === "rented") return "bg-amber-500";
  return "bg-rose-500";
}

export default function Home() {
  const { user, token } = useAuthStore();
  const [filters, setFilters] = useState({
    type: "",
    location: "",
    pickupDate: "",
    returnDate: "",
  });
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedVehicle, setSelectedVehicle] = useState(null);
  const [modalPickupDate, setModalPickupDate] = useState("");
  const [modalReturnDate, setModalReturnDate] = useState("");
  const [bookingLoading, setBookingLoading] = useState(false);
  const [bookingId, setBookingId] = useState("");

  const canSearch = useMemo(
    () => Boolean(filters.pickupDate && filters.returnDate),
    [filters.pickupDate, filters.returnDate],
  );

  const handleFilterChange = (field, value) => {
    setFilters((prev) => ({ ...prev, [field]: value }));
  };

  const searchVehicles = async (event) => {
    event.preventDefault();
    if (!canSearch) {
      toast.error("Please select pickup and return dates.");
      return;
    }

    setLoading(true);
    try {
      const params = { status: "available" };
      if (filters.type) params.type = filters.type;
      if (filters.location) params.location = filters.location;
      const { data } = await axios.get(`${API_BASE}/api/vehicles`, { params });
      setVehicles(Array.isArray(data) ? data : []);
      if (!Array.isArray(data) || data.length === 0) {
        toast("No available vehicles found for these filters.");
      }
    } catch {
      toast.error("Unable to fetch vehicles right now.");
      setVehicles([]);
    } finally {
      setLoading(false);
    }
  };

  const openModal = (vehicle) => {
    setSelectedVehicle(vehicle);
    setModalPickupDate(filters.pickupDate);
    setModalReturnDate(filters.returnDate);
    setBookingId("");
  };

  const closeModal = () => {
    setSelectedVehicle(null);
    setBookingLoading(false);
  };

  const confirmBooking = async () => {
    if (!user?.id || !token) {
      toast.error("Please login first to confirm booking.");
      return;
    }
    if (!modalPickupDate || !modalReturnDate) {
      toast.error("Pickup and return dates are required.");
      return;
    }

    setBookingLoading(true);
    try {
      const { data } = await axios.post(
        `${API_BASE}/api/bookings`,
        {
          customer_id: user.id,
          vehicle_id: selectedVehicle.id,
          pickup_date: new Date(modalPickupDate).toISOString(),
          return_date: new Date(modalReturnDate).toISOString(),
          notes: "Booked from Home booking modal",
        },
        { headers: { Authorization: `Bearer ${token}` } },
      );
      setBookingId(data.id);
      toast.success("Booking confirmed successfully.");
    } catch (error) {
      const detail = error?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Booking failed. Please try another vehicle.");
    } finally {
      setBookingLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <Toaster position="top-right" />

      <section className="mx-auto max-w-6xl px-4 py-12">
        <div className="rounded-3xl bg-gradient-to-br from-indigo-700 via-indigo-600 to-violet-600 p-8 text-white shadow-xl">
          <h1 className="text-3xl font-bold md:text-5xl">Book your perfect ride in under 2 minutes</h1>
          <p className="mt-3 max-w-2xl text-indigo-100">
            AI-powered rental - instant booking, zero paperwork
          </p>

          <form onSubmit={searchVehicles} className="mt-7 grid gap-3 md:grid-cols-5">
            <select
              value={filters.type}
              onChange={(e) => handleFilterChange("type", e.target.value)}
              className="rounded-xl border border-indigo-300 bg-white px-3 py-2 text-slate-800"
            >
              <option value="">Vehicle type</option>
              {VEHICLE_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type.toUpperCase()}
                </option>
              ))}
            </select>
            <input
              type="date"
              value={filters.pickupDate}
              onChange={(e) => handleFilterChange("pickupDate", e.target.value)}
              className="rounded-xl border border-indigo-300 bg-white px-3 py-2 text-slate-800"
            />
            <input
              type="date"
              value={filters.returnDate}
              onChange={(e) => handleFilterChange("returnDate", e.target.value)}
              className="rounded-xl border border-indigo-300 bg-white px-3 py-2 text-slate-800"
            />
            <select
              value={filters.location}
              onChange={(e) => handleFilterChange("location", e.target.value)}
              className="rounded-xl border border-indigo-300 bg-white px-3 py-2 text-slate-800"
            >
              <option value="">Location</option>
              {LOCATIONS.map((location) => (
                <option key={location} value={location}>
                  {location}
                </option>
              ))}
            </select>
            <button
              type="submit"
              className="rounded-xl bg-slate-900 px-4 py-2 font-semibold text-white hover:bg-slate-800"
            >
              {loading ? "Searching..." : "Search Available Vehicles"}
            </button>
          </form>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-12">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {vehicles.map((vehicle) => (
            <article key={vehicle.id} className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="flex items-start justify-between">
                <h3 className="text-lg font-semibold">
                  {vehicle.brand} {vehicle.model_name}
                </h3>
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700">
                  <span className={`h-2 w-2 rounded-full ${statusDotClass(vehicle.status)}`} />
                  {vehicle.status}
                </span>
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className="rounded-md bg-indigo-100 px-2 py-1 text-xs font-medium text-indigo-700">
                  {vehicle.type}
                </span>
                <span className="text-sm text-slate-500">{vehicle.location}</span>
              </div>
              <p className="mt-3 text-xl font-bold text-indigo-600">${vehicle.daily_rate}/day</p>
              <button
                type="button"
                onClick={() => openModal(vehicle)}
                className="mt-4 w-full rounded-xl bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500"
              >
                Book Now
              </button>
            </article>
          ))}
        </div>
      </section>

      {selectedVehicle && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
            <h2 className="text-xl font-bold text-slate-900">Confirm Booking</h2>
            <p className="mt-1 text-sm text-slate-600">
              {selectedVehicle.brand} {selectedVehicle.model_name} - {selectedVehicle.type} - $
              {selectedVehicle.daily_rate}/day
            </p>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <input
                type="date"
                value={modalPickupDate}
                onChange={(e) => setModalPickupDate(e.target.value)}
                className="rounded-xl border border-slate-300 px-3 py-2"
              />
              <input
                type="date"
                value={modalReturnDate}
                onChange={(e) => setModalReturnDate(e.target.value)}
                className="rounded-xl border border-slate-300 px-3 py-2"
              />
            </div>

            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={closeModal}
                className="w-full rounded-xl border border-slate-300 px-4 py-2 text-slate-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmBooking}
                disabled={bookingLoading}
                className="w-full rounded-xl bg-emerald-600 px-4 py-2 font-semibold text-white disabled:opacity-60"
              >
                {bookingLoading ? "Confirming..." : "Confirm Booking"}
              </button>
            </div>

            {bookingId && (
              <div className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-700">
                Booking ID: <span className="font-semibold">{bookingId}</span>
                <div className="mt-1">Chat with our AI for any changes.</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
