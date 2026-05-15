CREATE TABLE registration_fees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hackathon_id UUID NOT NULL REFERENCES hackathons(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    user_id UUID NOT NULL REFERENCES users(id),
    wallet_address TEXT NOT NULL,
    tx_signature TEXT NOT NULL UNIQUE,
    amount_usdc BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX registration_fees_hackathon_id_idx ON registration_fees(hackathon_id);
CREATE INDEX registration_fees_created_at_idx ON registration_fees(created_at);
