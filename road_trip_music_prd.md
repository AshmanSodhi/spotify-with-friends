# PRD --- Road Trip Shared Spotify Music Queue

## 1. Product Overview

### Product Name

Road Trip Music Requester

### Product Summary

A lightweight web application that lets a group of friends on a road
trip search Spotify songs and add them to the host's Spotify playback
queue.

The host connects **one Spotify account** to the application. Friends do
**not** need Spotify accounts and do **not** authenticate with Spotify.
They join a shared room using a room code or link, search for songs, and
add songs to the host's Spotify queue.

### Core Principle

Spotify is the source of truth for playback and the queue.

The application must **not maintain its own queue database** and must
**not display the Spotify queue on the website**.

------------------------------------------------------------------------

# 2. Goals

## Primary Goals

1.  Allow the host to connect their Spotify account.
2.  Allow the host to create a temporary road-trip room.
3.  Allow friends to join the room without Spotify authentication.
4.  Allow friends to search Spotify's catalog.
5.  Allow friends to add a selected Spotify track directly to the host's
    Spotify queue.
6.  Keep the user experience fast and mobile-friendly.
7.  Keep Spotify credentials/tokens on the backend and never expose them
    to friends.
8.  Require minimal setup for the host after the initial Spotify
    authorization.

## Secondary Goals

1.  Show useful confirmation after a song is added.
2.  Show who added a song only as an ephemeral UI confirmation, if
    desired; this must not become persistent queue storage.
3.  Prevent accidental duplicate requests within a short period.
4.  Provide a simple host/admin interface for room creation and Spotify
    connection status.

------------------------------------------------------------------------

# 3. Non-Goals

The following are explicitly out of scope for V1:

-   Showing the Spotify queue on the website.
-   Maintaining a separate application-side queue.
-   Storing queue items in PostgreSQL or another database.
-   Reordering Spotify's queue from the website.
-   Removing arbitrary songs from Spotify's queue through the website.
-   Friend Spotify authentication.
-   User accounts for friends.
-   Google authentication.
-   Voting/ranking songs.
-   Playlists.
-   Recommendations.
-   AI music recommendations.
-   Analytics.
-   Music playback directly inside the website.
-   Downloading or streaming Spotify audio through the application.
-   Building a custom Spotify player.
-   Managing multiple host Spotify accounts in one room.

------------------------------------------------------------------------

# 4. User Roles

## 4.1 Host

The host is the person whose Spotify account controls playback.

Capabilities:

-   Connect Spotify.
-   Create a room.
-   Share the room link/code.
-   See room status.
-   End the room.
-   Add songs themselves.
-   Use their normal Spotify application/device for playback.

The host must authorize the application with Spotify.

## 4.2 Guest

Guests are road-trip participants.

Capabilities:

-   Join a room.
-   Enter a display name.
-   Search Spotify.
-   View search results.
-   Add songs to the host's Spotify queue.

Guests:

-   Do not need Spotify accounts.
-   Do not need Spotify authorization.
-   Do not receive the host's Spotify credentials or tokens.

------------------------------------------------------------------------

# 5. User Journey

## 5.1 Host Setup

1.  Host opens the application.
2.  Host clicks `Connect Spotify`.
3.  Host is redirected to Spotify authorization.
4.  Host grants the required permissions.
5.  Backend receives the authorization callback.
6.  Backend securely stores the refresh token.
7.  Host clicks `Create Room`.
8.  Backend creates a temporary room.
9.  Host receives:
    -   Room code
    -   Shareable room URL
    -   QR code
10. Host shares the URL/QR code with friends.

## 5.2 Guest Journey

1.  Guest opens the shared room URL.
2.  Guest enters a display name.
3.  Guest joins the room.
4.  Guest sees a song search interface.
5.  Guest searches for a song.
6.  Guest selects a Spotify track.
7.  Guest clicks `Add to Queue`.
8.  Backend adds the Spotify track to the host's Spotify playback queue.
9.  Guest sees a success confirmation.
10. Guest can immediately search for another song.

## 5.3 Host Playback

The host continues using the Spotify application normally.

The website does not replace Spotify playback.

Example:

``` text
Host phone
    |
    +--> Spotify app
           |
           +--> Music playback
           +--> Actual Spotify queue

Friends' phones
    |
    +--> Road Trip Website
           |
           +--> Search Spotify
           +--> Add selected track
```

------------------------------------------------------------------------

# 6. Functional Requirements

## FR-1: Spotify Host Authorization

The system shall support Spotify authorization for the host account.

The authorization must be performed only by the host.

Recommended authorization approach:

-   Authorization Code with PKCE for the web application.
-   Backend-managed token lifecycle.
-   Never expose client secrets or refresh tokens to the browser.

Required Spotify permissions should be limited to the minimum needed for
the application.

At minimum, the implementation needs permission to:

-   Search Spotify content.
-   Add an item to the user's playback queue.

If the implementation uses additional playback/account endpoints,
request only the corresponding required scopes.

------------------------------------------------------------------------

# 7. Spotify Token Management

The backend shall manage Spotify authorization tokens.

## Requirements

-   Store refresh tokens securely.
-   Never send refresh tokens to clients.
-   Never put Spotify client secrets in frontend code.
-   Automatically refresh expired access tokens.
-   Handle revoked/invalid refresh tokens gracefully.
-   If authorization becomes invalid, show the host a clear
    `Reconnect Spotify` action.

Conceptual flow:

``` text
Browser
   |
   | OAuth
   v
Spotify
   |
   | Authorization callback
   v
Backend
   |
   +--> access token
   +--> refresh token
   |
   v
Spotify Web API
```

------------------------------------------------------------------------

# 8. Room Management

## Room Creation

The host can create a room after Spotify is connected.

A room should contain only the minimum metadata required:

``` text
room_id
room_code
host_session/user identifier
created_at
expires_at
status
```

The application does not store queue contents.

## Room Code

The room code should be:

-   Short.
-   Human-readable.
-   Case-insensitive.
-   Hard to guess.
-   Unique among active rooms.

Example:

``` text
7XK92A
```

## Room URL

Example:

``` text
https://<domain>/join/7XK92A
```

## Room Expiration

Rooms should be temporary.

Recommended default:

-   Expire after 12--24 hours.
-   Host can manually end a room.

Expired rooms must reject new guest joins and song additions.

------------------------------------------------------------------------

# 9. Guest Identity

Guests do not need accounts.

When joining:

``` text
What's your name?

[ Rahul ]

[ Join Room ]
```

The backend may issue a short-lived guest session/token after joining.

The guest session should contain:

``` text
room_id
guest_id
display_name
expires_at
```

The guest identity is only needed for room-level access control and UI
messaging.

No permanent user profile is required.

------------------------------------------------------------------------

# 10. Spotify Search

The frontend shall provide a search field.

Example:

``` text
Search for a song...

[ Blinding Lights ]
```

The frontend calls the backend rather than Spotify directly.

Example:

``` http
GET /api/rooms/{room_code}/search?q=blinding%20lights
```

Backend:

1.  Validate guest session.
2.  Validate room.
3.  Obtain a valid Spotify access token for the host.
4.  Call Spotify Search API.
5.  Return only the fields needed by the frontend.

Recommended response fields:

``` json
{
  "tracks": [
    {
      "id": "spotify-track-id",
      "uri": "spotify:track:...",
      "name": "Blinding Lights",
      "artists": ["The Weeknd"],
      "album": "After Hours",
      "album_image": "https://..."
    }
  ]
}
```

The backend should not expose unnecessary Spotify/account information.

------------------------------------------------------------------------

# 11. Add Song to Spotify Queue

When a guest selects a track:

``` http
POST /api/rooms/{room_code}/queue
```

Request:

``` json
{
  "track_uri": "spotify:track:..."
}
```

Backend flow:

``` text
Validate guest
      |
Validate room
      |
Validate Spotify authorization
      |
Validate track URI
      |
Get valid host access token
      |
Call Spotify Add to Queue API
      |
Return success/failure
```

The application must not save the track as a queue record.

Spotify remains the source of truth.

------------------------------------------------------------------------

# 12. Queue Storage Policy

## Critical Requirement

The application must NOT create or maintain its own queue.

Do not create:

``` text
queue table
queue collection
queue JSON file
queue cache
queue state in localStorage
```

The application only performs:

``` text
Search Spotify
       |
       v
Select Spotify track
       |
       v
Add directly to Spotify queue
```

The website does not display or synchronize the Spotify queue.

If the host changes the queue directly in Spotify, there is nothing in
the website that needs synchronization.

------------------------------------------------------------------------

# 13. Duplicate Handling

Spotify is responsible for the actual queue.

V1 should not attempt to maintain a copy of the queue to detect
duplicates.

The application may implement a very short client-side request lock to
prevent accidental double-clicks, for example:

``` text
User clicks Add
      |
Button disabled for 1–2 seconds
      |
Request sent once
```

This is only UI protection and must not become queue storage.

------------------------------------------------------------------------

# 14. API Design

Recommended FastAPI routes:

## Health

``` http
GET /api/health
```

Response:

``` json
{
  "status": "ok"
}
```

## Host Spotify Login

``` http
GET /api/auth/spotify/login
```

Starts Spotify OAuth.

## Spotify Callback

``` http
GET /api/auth/spotify/callback
```

Handles Spotify authorization callback.

## Host Status

``` http
GET /api/host/spotify/status
```

Example:

``` json
{
  "connected": true
}
```

## Create Room

``` http
POST /api/rooms
```

Requires authenticated host session.

Response:

``` json
{
  "room_code": "7XK92A",
  "join_url": "https://example.com/join/7XK92A"
}
```

## Join Room

``` http
POST /api/rooms/{room_code}/join
```

Request:

``` json
{
  "display_name": "Rahul"
}
```

Response:

``` json
{
  "guest_token": "...",
  "room_code": "7XK92A"
}
```

## Search

``` http
GET /api/rooms/{room_code}/search?q=...
```

Requires valid guest or host room session.

## Add Track

``` http
POST /api/rooms/{room_code}/queue
```

Request:

``` json
{
  "track_uri": "spotify:track:..."
}
```

Response:

``` json
{
  "success": true,
  "message": "Added to Spotify queue"
}
```

------------------------------------------------------------------------

# 15. Error Handling

The backend must return clear, machine-readable errors.

## Spotify not connected

``` json
{
  "error": "SPOTIFY_NOT_CONNECTED",
  "message": "The host needs to connect Spotify."
}
```

## Spotify authorization expired/revoked

``` json
{
  "error": "SPOTIFY_REAUTH_REQUIRED",
  "message": "The host needs to reconnect Spotify."
}
```

## Room expired

``` json
{
  "error": "ROOM_EXPIRED",
  "message": "This road trip room has expired."
}
```

## Invalid track

``` json
{
  "error": "INVALID_TRACK",
  "message": "The selected Spotify track is invalid."
}
```

## Spotify API failure

``` json
{
  "error": "SPOTIFY_API_ERROR",
  "message": "Spotify could not add this song right now. Please try again."
}
```

Do not expose raw Spotify access tokens, client secrets, stack traces,
or internal errors to users.

------------------------------------------------------------------------

# 16. Frontend Requirements

## Host Home Page

The host landing page should contain:

``` text
ROAD TRIP MUSIC

Connect your Spotify account

[ Connect Spotify ]

[ Create Room ]
```

If Spotify is already connected:

``` text
Spotify: Connected ✓

[ Create Room ]
```

## Room Created Page

Display:

``` text
Your room is ready!

Room Code
7XK92A

[ Copy Link ]

[ Show QR Code ]

Waiting for friends...
```

The host can also access the same search interface if desired.

## Guest Join Page

``` text
🚗 Road Trip Music

Room: 7XK92A

Your name
[____________]

[ Join Room ]
```

## Main Music Page

``` text
🚗 ROAD TRIP MUSIC

🔍 Search Spotify
[________________________]

Search Results

┌──────────────────────────────┐
│ Album Art                    │
│ Blinding Lights              │
│ The Weeknd                   │
│ After Hours                  │
│                              │
│              [ + Add ]       │
└──────────────────────────────┘
```

After successful addition:

``` text
✓ Added to Spotify queue
```

The user can continue searching.

------------------------------------------------------------------------

# 17. Mobile-First UX

The primary use case is smartphones inside a car.

The interface must therefore:

-   Work well on small screens.
-   Use large touch targets.
-   Avoid tiny buttons.
-   Keep the search field prominent.
-   Minimize navigation.
-   Avoid unnecessary animations.
-   Show clear success/error states.
-   Work on both Android and iOS browsers.

The guest flow should require as few taps as possible:

``` text
Open link
   ↓
Enter name
   ↓
Search
   ↓
Tap Add
```

------------------------------------------------------------------------

# 18. Security Requirements

## Spotify Credentials

Never expose:

-   Spotify client secret.
-   Spotify refresh token.
-   Backend session secrets.
-   Host credentials.

## Guest Access

Guests should only be able to:

-   Access the room they joined.
-   Search Spotify through the application.
-   Add tracks while the room is active.

Guests must not be able to:

-   Read Spotify tokens.
-   Control arbitrary Spotify accounts.
-   Create Spotify authorization requests for other users.
-   Access host account information.

## Rate Limiting

Implement basic rate limiting for:

-   Search.
-   Add-to-queue requests.
-   Room join requests.

Recommended initial limits can be simple and conservative, then adjusted
based on testing.

------------------------------------------------------------------------

# 19. Backend Architecture

Recommended stack:

``` text
Backend:
FastAPI
Python
httpx
Pydantic

Frontend:
Next.js
React
Tailwind CSS

Storage:
Small relational database for room/session metadata only.
No queue storage.

Deployment:
Backend and frontend may be deployed separately.
```

A database is optional for the smallest prototype, but if used, it must
only store room/session metadata and never Spotify queue contents.

------------------------------------------------------------------------

# 20. Suggested Project Structure

``` text
road-trip-music/
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx
│   │   ├── host/
│   │   ├── join/
│   │   │   └── [roomCode]/
│   │   └── room/
│   │       └── [roomCode]/
│   │
│   ├── components/
│   │   ├── SearchBar.tsx
│   │   ├── SearchResults.tsx
│   │   ├── TrackCard.tsx
│   │   ├── JoinRoom.tsx
│   │   └── RoomHeader.tsx
│   │
│   └── lib/
│       └── api.ts
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── spotify/
│   │   │   ├── auth.py
│   │   │   ├── client.py
│   │   │   └── models.py
│   │   ├── rooms/
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   └── models.py
│   │   └── auth/
│   │       └── router.py
│   │
│   ├── requirements.txt
│   └── .env.example
│
└── README.md
```

------------------------------------------------------------------------

# 21. Environment Variables

Use environment variables for secrets.

Example:

``` env
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=

SESSION_SECRET=

DATABASE_URL=
FRONTEND_URL=
```

Do not commit `.env` files containing real credentials.

Provide `.env.example` with placeholder values.

------------------------------------------------------------------------

# 22. Spotify Integration Rules

The implementation must use Spotify's official Web API.

Important operations:

### Authorization

Use Spotify OAuth.

### Search

Use Spotify Search API.

### Add to queue

Use Spotify's Add Item to Playback Queue endpoint.

The application should not attempt to scrape Spotify pages or use
unofficial Spotify endpoints.

The implementation must handle Spotify API errors and rate limits
gracefully.

------------------------------------------------------------------------

# 23. Session Strategy

There are two logical sessions:

## Host Session

Identifies the host who owns the connected Spotify account.

## Guest Session

Identifies a guest within a specific room.

A guest session does not represent a Spotify account.

Recommended approach:

``` text
Host
  |
  +--> Secure HTTP-only session cookie

Guest
  |
  +--> Short-lived signed room token
```

The exact session implementation may be chosen by the coding LLM as long
as the security requirements are satisfied.

------------------------------------------------------------------------

# 24. Performance Requirements

Target:

-   Search response: ideally \< 2 seconds under normal conditions.
-   Add-to-queue response: ideally \< 2 seconds under normal conditions.
-   Initial page load: optimized for mobile networks.
-   Search should debounce requests to avoid unnecessary Spotify API
    calls.

Recommended search debounce:

``` text
300–500 ms
```

Do not send a Spotify API request for every keystroke.

------------------------------------------------------------------------

# 25. UX States

The UI must handle:

### Search

``` text
Idle
Searching...
Results
No results
Search error
```

### Add

``` text
Ready
Adding...
Added ✓
Failed
Retry
```

### Spotify

``` text
Connected ✓
Not connected
Authorization required
Authorization expired
Spotify unavailable
```

### Room

``` text
Creating...
Active
Expired
Ended
Invalid
```

------------------------------------------------------------------------

# 26. Acceptance Criteria

## Spotify

-   [ ] Host can connect one Spotify account.
-   [ ] Spotify tokens are handled only by the backend.
-   [ ] Friends never need Spotify authorization.
-   [ ] Host authorization can be refreshed without manually logging in
    every hour.
-   [ ] Revoked authorization produces a clear reconnect flow.

## Rooms

-   [ ] Host can create a room.
-   [ ] Room receives a unique code.
-   [ ] Host receives a shareable URL.
-   [ ] Guest can join with room code/link.
-   [ ] Guest can provide a display name.
-   [ ] Expired rooms reject new requests.

## Search

-   [ ] Guest can search Spotify.
-   [ ] Search results show track name.
-   [ ] Search results show artist.
-   [ ] Search results show album/artwork when available.
-   [ ] Search requests are debounced.
-   [ ] Spotify errors are handled gracefully.

## Queue Addition

-   [ ] Guest can select a track.
-   [ ] Track is added directly to the host's Spotify queue.
-   [ ] Website does not store the queue.
-   [ ] Website does not display the queue.
-   [ ] Double-clicking Add does not intentionally create duplicate
    requests.
-   [ ] Failed additions provide a retry option.

## Security

-   [ ] Spotify client secret is backend-only.
-   [ ] Spotify refresh token is backend-only.
-   [ ] Guest cannot access host credentials.
-   [ ] Guest cannot control an account outside the active room.
-   [ ] API endpoints have basic rate limiting.

------------------------------------------------------------------------

# 27. V1 Definition of Done

V1 is complete when the following scenario works end-to-end:

``` text
1. Host opens website.
2. Host connects Spotify.
3. Host creates room.
4. Host shares room URL.
5. Friend opens URL.
6. Friend enters name.
7. Friend joins room.
8. Friend searches "Blinding Lights".
9. Search results appear.
10. Friend clicks "Add to Queue".
11. Backend calls Spotify Add to Queue API.
12. Spotify confirms the request.
13. Friend sees "Added to Spotify queue".
14. Host's Spotify app can play the queued song.
```

No queue database or queue UI should be required for this flow.

------------------------------------------------------------------------

# 28. Future Features --- Not V1

Possible future additions:

-   Upvote/downvote requests.
-   Request history.
-   Guest request limits.
-   Host-only skip controls.
-   "Request approved" workflow.
-   QR-code room joining.
-   Guest avatars.
-   Song request notifications.
-   Temporary room playlist/history.
-   Smart duplicate detection using Spotify's current queue.
-   AI-based road-trip music recommendations.
-   Mood/energy controls.
-   Hindi/English music balance.
-   Artist cooldown.
-   "No repeat in last N songs."
-   Host moderation tools.

These should not be implemented unless explicitly requested.

------------------------------------------------------------------------

# 29. Important Implementation Constraint

The coding agent must not over-engineer this project.

The simplest working architecture is preferred.

Especially:

-   Do not create a queue table.
-   Do not create a queue synchronization service.
-   Do not create WebSockets for queue synchronization.
-   Do not poll Spotify's queue because the website does not display it.
-   Do not implement friend Spotify accounts.
-   Do not implement unnecessary authentication providers.
-   Do not build a custom audio player.

The application is fundamentally:

``` text
Host Spotify OAuth
        +
Temporary Room
        +
Spotify Search
        +
Add Track to Host Spotify Queue
```

Keep V1 focused on this functionality.
