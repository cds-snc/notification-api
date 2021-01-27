-- Create `reader` role with necessary password per default 
-- postgresql configuration.
create user reader with encrypted password 'postgres';
