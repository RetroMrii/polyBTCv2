from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerifiedSources:
    """
    Source-origin and fee-policy assertions supplied
    by a trusted upstream data adapter.

    These flags must not be inferred merely because
    timestamp fields contain non-null values.

    Production v1.1 timestamp mapping:

      reference_timestamp:
          RTDS / Chainlink source event time

      yes_book_timestamp:
          YES CLOB response timestamp

      no_book_timestamp:
          NO CLOB response timestamp

      observed_at:
          Local collector CSV observation/write time

    fee_policy_verified must not be set True in
    prospective operation until the applicable
    fee policy has been independently verified.
    """

    reference_source_verified: bool
    yes_book_source_verified: bool
    no_book_source_verified: bool
    fee_policy_verified: bool
