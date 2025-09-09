# Brightspace MCP Server

This package implements a local [MCP](https://github.com/fixie-ai/mcp) server that exposes
Brightspace (Valence) APIs via a set of tools.  Running the server
enables an autonomous agent to interact with your Brightspace instance
through the MCP protocol.

## Features

- Uses OAuth2 refresh tokens to manage authentication automatically.
- Provides convenience methods for common operations:
  - `bs.whoami` – Identify the current authenticated user.
  - `bs.list_org_units` – List organizational units (e.g. courses, semesters).
  - `bs.list_courses` – Filter and list course offerings (OrgUnitTypeId=3).
  - `bs.list_users` – Search and paginate through users.
  - `bs.get_user` – Retrieve a single user by ID.
  - `bs.my_enrollments` – List enrollments for the current user.
  - `bs.list_announcements` – List news items in a course.
  - `bs.list_users` – Search and paginate through users.
  - `bs.create_announcement` – Post news items in a course.
- Includes a generic `bs.request` tool for arbitrary HTTP requests against
  any Brightspace endpoint.

## Installation

Install the package in a virtual environment using pip:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

The `-e` flag installs the package in editable mode so changes to the code
are reflected immediately.

## Configuration

The server expects several environment variables to be set.  You can
configure these via a `.env` file in the project root or via your shell
environment:

- **BS_BASE_URL** – Base URL of your Brightspace instance (e.g. `https://d2l.example.com`).
- **BS_CLIENT_ID** – OAuth2 client ID from your Brightspace registration.
- **BS_CLIENT_SECRET** – OAuth2 client secret.
- **BS_REFRESH_TOKEN** – Refresh token obtained through the Brightspace
  OAuth2 flow.
- **BS_LP_VERSION** *(optional)* – Learning Platform API version.  Defaults to `1.46`.
- **BS_LE_VERSION** *(optional)* – Learning Environment API version.  Defaults to `1.74`.
- **BS_DEFAULT_VERSION** *(optional)* – Default API version used by the generic request tool.

An example `.env` file is provided:

```env
BS_BASE_URL=https://your.brightspace.host
BS_CLIENT_ID=your_client_id
BS_CLIENT_SECRET=your_client_secret
BS_REFRESH_TOKEN=your_refresh_token
BS_LP_VERSION=1.46
BS_LE_VERSION=1.74
BS_DEFAULT_VERSION=1.46
```

Copy `.env.example` to `.env` and populate the values before running the server.

## Running the Server

Run the server using the script exposed in the package.  Ensure your
configuration is loaded via `.env` or the environment.

```sh
brightspace-mcp
# or equivalently
python -m brightspace_mcp.main
```

The server communicates over standard input and output as required by
MCP.  Tools are invoked by sending JSON messages identifying the tool
and arguments (e.g. `{ "tool": "bs.whoami", "arguments": {} }`).

## Direct CLI (no MCP client)

Install the package (editable or normal), set `.env`, then use the direct CLI
to exercise core functions:

```sh
brightspace-mcp-cli whoami
brightspace-mcp-cli list-courses --page-size 5
brightspace-mcp-cli create-announcement 12345 "Welcome" "<p>Hello!</p>"
brightspace-mcp-cli api-call GET /d2l/api/lp/1.46/users/ --params '{"pageSize":10}'
```

## Quick Self-Test (no MCP client needed)

If you just want to verify your credentials and connectivity before wiring
this into an MCP client, run the built-in self-test:

```sh
brightspace-mcp-selftest
# or
python -m brightspace_mcp.selftest
```

This will:
- Refresh an access token using `BS_REFRESH_TOKEN`
- Call `whoami` and print the authenticated user
- Fetch the first 5 courses and print the response

If anything fails (missing env vars, auth errors), you’ll see a concise error.

## Examples

Below are example MCP requests encoded as JSON.  Each request is a
single object with a `tool` field and an `arguments` field:

```json
{ "tool": "bs.whoami", "arguments": {} }

{ "tool": "bs.list_courses", "arguments": { "page_size": 50 } }

{ "tool": "bs.create_announcement", "arguments": {
  "org_unit_id": 12345,
  "title": "Welcome!",
  "html": "<p>Hello students, welcome to the course.</p>"
} }

{ "tool": "bs.request", "arguments": {
  "method": "GET",
  "path": "/d2l/api/lp/1.46/users/",
  "params": { "pageSize": 10 }
} }

{ "tool": "bs.list_org_units", "arguments": { "org_unit_type_id": 3, "page_size": 50 } }

{ "tool": "bs.list_users", "arguments": { "search_term": "smith", "page_size": 25 } }

{ "tool": "bs.get_user", "arguments": { "user_id": 1234 } }

{ "tool": "bs.my_enrollments", "arguments": { "page_size": 50 } }

{ "tool": "bs.list_announcements", "arguments": { "org_unit_id": 12345, "page_size": 20 } }

{ "tool": "bs.get_content_toc", "arguments": { "org_unit_id": 12345 } }
```

If you need a wrapper around additional endpoints, such as grade or
content operations, consider adding more convenience methods to
`brightspace_mcp.brightspace.BrightspaceClient` and corresponding tools
in `brightspace_mcp.main`.
