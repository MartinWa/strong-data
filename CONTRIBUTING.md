# Contributing

Thanks for helping. Setup, checks and the development container are in
[development](docs/development.md); this page covers the rules and the paperwork.

## Before opening a pull request

Run the checks listed under [commands](docs/development.md#commands) and make sure
CI is green. Discuss larger changes in an issue first.

## Rules

- Use Django migrations for every schema change.
- Keep fixtures, screenshots and examples wholly synthetic. Never commit personal
  data, CSV files, databases, backups, secrets or `.env` files;
  [SECURITY.md](SECURITY.md) says what counts as personal data.
- New behaviour needs a test, and code stays free of comments unless a change
  explicitly requires them.

## Contributor agreement

Before your first pull request can be merged, sign the
[Contributor License Agreement](CLA.md). An app comments on your pull request with
a signing link; click it once and the signature covers your future contributions
too. You keep the copyright in your contribution.

The agreement matters because the project is dual licensed: it is published under
the PolyForm Noncommercial License 1.0.0 and also offered commercially, and the
agreement is what lets a contribution be part of both. If you contribute in the
course of employment, read section 6 first: your employer may own the work, and an
authorised person has to sign for the entity. There is no Developer Certificate of
Origin (`Signed-off-by`), because a DCO certifies distribution under the current
licence only and does not permit relicensing.

Signatures are collected by [CLA Assistant](https://cla-assistant.io), a free
GitHub app, and stored outside this repository, so contributor accounts never
enter it.

## License

Contributions are licensed under the PolyForm Noncommercial License 1.0.0 (see
[LICENSE](LICENSE) and [NOTICE](NOTICE)) and under the terms of the Contributor
License Agreement.
