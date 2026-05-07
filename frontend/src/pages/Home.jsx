import { useMemo, useState } from "react";
import axios from "axios";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

export default function Home({ onSelectVehicle }) {
  const [filters, setFilters] = useState({
    type: "",
    status: "available",
    location: "",
    pickupDate: "",
    returnDate: "",
  });
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const hasDates = useMemo(
    () => Boolean(filters.pickupDate && filters.returnDate),
    [filters.pickupDate, filters.returnDate],
  );

  const handleFilterChange = (field, value) => {
    setFilters((prev) => ({ ...prev, [field]: value }));
  };

  const searchVehicles = async (event) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (filters.type) params.type = filters.type;
      if (filters.status) params.status = filters.status;
      if (filters.location) params.location = filters.location;
      const { data } = await axios.get(`${API_BASE}/vehicles`, { params });
      setVehicles(Array.isArray(data) ? data : []);
    } catch {
      setError("Unable to fetch vehicles right now.");
      setVehicles([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <section className="mx-auto max-w-6xl px-4 py-12">
        <div className="rounded-3xl bg-indigo-600 p-8 text-white shadow-xl">
          <h1 className="text-3xl font-bold md:text-4xl">RideSwift</h1>
          <p className="mt-3 max-w-2xl text-indigo-100">
            Book the right vehicle in seconds with real-time availability and smart recommendations.
          </p>
          <form className="mt-6 grid gap-3 md:grid-cols-5" onSubmit={searchVehicles}>
            <select
              value={filters.type}
              onChange={(e) => handleFilterChange("type", e.target.value)}
              className="rounded-xl border border-indigo-300 bg-white px-3 py-2 text-slate-800"
            >
              <option value="">All types</option>
              <option value="car">Car</option>
              <option value="bike">Bike</option>
              <option value="suv">SUV</option>
              <option value="van">Van</option>
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
            <input
              type="text"
              value={filters.location}
              onChange={(e) => handleFilterChange("location", e.target.value)}
              placeholder="Location"
              className="rounded-xl border border-indigo-300 bg-white px-3 py-2 text-slate-800"
            />
            <button
              type="submit"
              className="rounded-xl bg-slate-900 px-4 py-2 font-medium text-white hover:bg-slate-800"
            >
              {loading ? "Searching..." : "Search"}
            </button>
          </form>
          {!hasDates && (
            <p className="mt-3 text-xs text-indigo-100">Tip: pick date range to proceed with booking flow.</p>
          )}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-12">
        {error && <p className="mb-4 rounded-xl bg-red-100 p-3 text-red-700">{error}</p>}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {vehicles.map((vehicle) => (
            <article key={vehicle.id} className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <div className="flex items-start justify-between">
                <h3 className="text-lg font-semibold">
                  {vehicle.brand} {vehicle.model}
                </h3>
                <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs font-medium text-emerald-700">
                  {vehicle.status}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-600">Type: {vehicle.type}</p>
              <p className="text-sm text-slate-600">Location: {vehicle.location}</p>
              <p className="mt-3 text-xl font-bold text-indigo-600">${vehicle.price_per_day}/day</p>
              <button
                type="button"
                onClick={() => onSelectVehicle?.(vehicle, filters.pickupDate, filters.returnDate)}
                className="mt-4 w-full rounded-xl bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500"
              >
                Select Vehicle
              </button>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
