import { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const STRIPE_PUBLISHABLE_KEY = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || "";

function getStoredToken() {
  return localStorage.getItem("token") || "";
}

function authHeaders() {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function daysBetween(startDate, endDate) {
  const start = new Date(startDate);
  const end = new Date(endDate);
  const ms = end.getTime() - start.getTime();
  return Math.max(1, Math.ceil(ms / (1000 * 60 * 60 * 24)));
}

async function loadStripeClient() {
  if (window.Stripe) return window.Stripe(STRIPE_PUBLISHABLE_KEY);
  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://js.stripe.com/v3/";
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.body.appendChild(script);
  });
  return window.Stripe ? window.Stripe(STRIPE_PUBLISHABLE_KEY) : null;
}

export default function BookingFlow({ customerId }) {
  const [step, setStep] = useState(1);
  const [vehicles, setVehicles] = useState([]);
  const [selectedVehicle, setSelectedVehicle] = useState(null);
  const [pickupDate, setPickupDate] = useState("");
  const [returnDate, setReturnDate] = useState("");
  const [insuranceFile, setInsuranceFile] = useState(null);
  const [insuranceUploaded, setInsuranceUploaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const totalPrice = useMemo(() => {
    if (!selectedVehicle || !pickupDate || !returnDate) return 0;
    return Number(selectedVehicle.price_per_day) * daysBetween(pickupDate, returnDate);
  }, [pickupDate, returnDate, selectedVehicle]);

  useEffect(() => {
    const fetchVehicles = async () => {
      try {
        const { data } = await axios.get(`${API_BASE}/vehicles`, { params: { status: "available" } });
        setVehicles(Array.isArray(data) ? data : []);
      } catch {
        setVehicles([]);
      }
    };
    fetchVehicles();
  }, []);

  const uploadInsurance = async () => {
    if (!customerId || !insuranceFile) return;
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", insuranceFile);
      await axios.post(`${API_BASE}/insurance/upload/${customerId}`, formData, {
        headers: { ...authHeaders(), "Content-Type": "multipart/form-data" },
      });
      setInsuranceUploaded(true);
      setMessage("Insurance uploaded successfully.");
    } catch {
      setError("Insurance upload failed.");
    } finally {
      setLoading(false);
    }
  };

  const confirmBooking = async () => {
    if (!selectedVehicle || !pickupDate || !returnDate || !customerId) {
      setError("Please complete all required booking fields.");
      return;
    }
    setLoading(true);
    setError("");
    setMessage("");
    try {
      if (STRIPE_PUBLISHABLE_KEY) {
        await loadStripeClient();
      }

      const { data } = await axios.post(
        `${API_BASE}/bookings`,
        {
          customer_id: customerId,
          vehicle_id: selectedVehicle.id,
          pickup_date: new Date(pickupDate).toISOString(),
          return_date: new Date(returnDate).toISOString(),
          total_price: Number(totalPrice.toFixed(2)),
          notes: insuranceUploaded ? "Insurance document uploaded" : null,
        },
        { headers: authHeaders() },
      );
      setMessage(`Booking created successfully: ${data.id}`);
      setStep(1);
      setSelectedVehicle(null);
      setPickupDate("");
      setReturnDate("");
      setInsuranceFile(null);
      setInsuranceUploaded(false);
    } catch {
      setError("Payment or booking confirmation failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="text-3xl font-bold text-slate-900">Booking Flow</h1>
      <p className="mt-2 text-sm text-slate-600">Step {step} of 3</p>
      {error && <p className="mt-4 rounded-xl bg-red-100 p-3 text-red-700">{error}</p>}
      {message && <p className="mt-4 rounded-xl bg-emerald-100 p-3 text-emerald-700">{message}</p>}

      {step === 1 && (
        <section className="mt-6">
          <h2 className="mb-4 text-xl font-semibold text-slate-900">1. Select Vehicle</h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {vehicles.map((vehicle) => (
              <button
                key={vehicle.id}
                type="button"
                onClick={() => {
                  setSelectedVehicle(vehicle);
                  setStep(2);
                }}
                className="rounded-2xl bg-white p-5 text-left shadow ring-1 ring-slate-200 hover:ring-indigo-400"
              >
                <p className="text-lg font-semibold">
                  {vehicle.brand} {vehicle.model}
                </p>
                <p className="text-sm text-slate-600">{vehicle.type}</p>
                <p className="text-sm text-slate-600">{vehicle.location}</p>
                <p className="mt-2 font-bold text-indigo-600">${vehicle.price_per_day}/day</p>
              </button>
            ))}
          </div>
        </section>
      )}

      {step === 2 && selectedVehicle && (
        <section className="mt-6 rounded-2xl bg-white p-6 shadow ring-1 ring-slate-200">
          <h2 className="text-xl font-semibold text-slate-900">2. Dates + Insurance Upload</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <input
              type="date"
              value={pickupDate}
              onChange={(e) => setPickupDate(e.target.value)}
              className="rounded-xl border border-slate-300 px-3 py-2"
            />
            <input
              type="date"
              value={returnDate}
              onChange={(e) => setReturnDate(e.target.value)}
              className="rounded-xl border border-slate-300 px-3 py-2"
            />
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <input type="file" accept=".pdf" onChange={(e) => setInsuranceFile(e.target.files?.[0] || null)} />
            <button
              type="button"
              onClick={uploadInsurance}
              disabled={!insuranceFile || loading}
              className="rounded-xl bg-indigo-600 px-4 py-2 font-medium text-white disabled:opacity-50"
            >
              Upload Insurance
            </button>
            <span className="text-sm text-slate-600">{insuranceUploaded ? "Uploaded" : "Not uploaded"}</span>
          </div>
          <div className="mt-6 flex gap-3">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="rounded-xl border border-slate-300 px-4 py-2 text-slate-700"
            >
              Back
            </button>
            <button
              type="button"
              onClick={() => setStep(3)}
              disabled={!pickupDate || !returnDate}
              className="rounded-xl bg-slate-900 px-4 py-2 font-medium text-white disabled:opacity-50"
            >
              Continue to Payment
            </button>
          </div>
        </section>
      )}

      {step === 3 && selectedVehicle && (
        <section className="mt-6 rounded-2xl bg-white p-6 shadow ring-1 ring-slate-200">
          <h2 className="text-xl font-semibold text-slate-900">3. Payment (Stripe.js)</h2>
          <p className="mt-2 text-sm text-slate-600">
            Vehicle: {selectedVehicle.brand} {selectedVehicle.model}
          </p>
          <p className="text-sm text-slate-600">
            Total: <span className="font-semibold text-indigo-600">${Number(totalPrice).toFixed(2)}</span>
          </p>
          <p className="mt-4 text-xs text-slate-500">
            Stripe publishable key is read from REACT_APP_STRIPE_PUBLISHABLE_KEY.
          </p>
          <div className="mt-6 flex gap-3">
            <button
              type="button"
              onClick={() => setStep(2)}
              className="rounded-xl border border-slate-300 px-4 py-2 text-slate-700"
            >
              Back
            </button>
            <button
              type="button"
              onClick={confirmBooking}
              disabled={loading}
              className="rounded-xl bg-emerald-600 px-4 py-2 font-medium text-white disabled:opacity-50"
            >
              {loading ? "Processing..." : "Pay & Confirm Booking"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
