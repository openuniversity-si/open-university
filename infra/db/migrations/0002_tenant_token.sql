-- The credential of a tenant at the port (INFRA-SVC 2, P3 F2; D-309): the sha256 of the bearer token the installation
-- registered with it. The token itself never reaches the infrastructure; a tenant without one cannot call the port.
alter table work.tenant add column token_sha256 text unique check (token_sha256 ~ '^[0-9a-f]{64}$');
