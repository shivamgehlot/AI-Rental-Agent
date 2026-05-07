-- Core tables
CREATE TABLE vehicles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  type VARCHAR(50),           -- sedan, SUV, EV
  plate VARCHAR(20) UNIQUE,
  status VARCHAR(20) DEFAULT 'available', -- available, rented, maintenance
  location_id UUID,
  daily_rate DECIMAL(10,2),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(100),
  email VARCHAR(100) UNIQUE,
  phone VARCHAR(20),
  profile JSONB,              -- stores preferences for personalization
  loyalty_points INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE bookings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID REFERENCES customers(id),
  vehicle_id UUID REFERENCES vehicles(id),
  pickup_date TIMESTAMPTZ,
  return_date TIMESTAMPTZ,
  status VARCHAR(20) DEFAULT 'pending', -- pending, confirmed, cancelled, completed
  total_amount DECIMAL(10,2),
  insurance_validated BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE insurance_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID REFERENCES customers(id),
  filename VARCHAR(200),
  storage_path TEXT,          -- MinIO path
  embedding_id VARCHAR(100),  -- Chroma vector ID
  uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast inventory lookups
CREATE INDEX idx_vehicles_status ON vehicles(status);
CREATE INDEX idx_bookings_dates ON bookings(pickup_date, return_date);