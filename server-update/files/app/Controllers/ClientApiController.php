<?php

declare(strict_types=1);

namespace App\Controllers;

use App\Core\Controller;
use App\Core\JsonResponse;
use App\Models\User;
use App\Services\ApiTokenService;
use App\Services\AuthService;
use App\Services\ClientApiService;
use Throwable;

final class ClientApiController extends Controller
{
    public function __construct(
        private readonly AuthService $authService,
        private readonly ApiTokenService $tokenService,
        private readonly ClientApiService $clientApiService,
        private readonly User $userModel,
    ) {
    }

    /**
     * Authentifiziert externe Clients und liefert einen Bearer-Token.
     */
    public function login(): void
    {
        $payload = $this->jsonPayload();
        $username = trim((string) ($payload['Username'] ?? $payload['username'] ?? ''));
        $password = (string) ($payload['Password'] ?? $payload['password'] ?? '');

        if ($username === '' || $password === '') {
            JsonResponse::error('Benutzername und Passwort sind erforderlich.', 400, 'INVALID_INPUT');
            return;
        }

        $user = $this->authService->findUserByLogin($username);
        if ($user === null || !password_verify($password, (string) $user['password_hash'])) {
            JsonResponse::error('Ungültige Anmeldedaten.', 401, 'INVALID_CREDENTIALS');
            return;
        }

        JsonResponse::send([
            'token' => $this->tokenService->createToken((int) $user['id']),
            'expiresIn' => $this->tokenService->lifetimeSeconds(),
        ]);
    }

    /**
     * Liefert alle Anlaesse fuer authentifizierte API-Clients.
     */
    public function anlaesse(): void
    {
        if (!$this->requireApiUser()) {
            return;
        }

        JsonResponse::send($this->clientApiService->listAnlaesse());
    }

    /**
     * Liefert alle Schuetzen beziehungsweise Standblaetter eines Anlasses.
     */
    public function shooters(array $params): void
    {
        if (!$this->requireApiUser()) {
            return;
        }

        $anlassId = (int) ($params['id'] ?? 0);
        if ($anlassId <= 0) {
            JsonResponse::error('Ungültiger Anlass.', 400, 'INVALID_ANLASS');
            return;
        }

        JsonResponse::send($this->clientApiService->listShooters($anlassId));
    }

    /**
     * Liefert nur seit einer Start-ID neu hinzugekommene Schuetzen.
     */
    public function newShooters(array $params): void
    {
        if (!$this->requireApiUser()) {
            return;
        }

        $anlassId = (int) ($params['id'] ?? 0);
        $sinceId = (int) ($_GET['sinceId'] ?? 0);

        if ($anlassId <= 0) {
            JsonResponse::error('Ungültiger Anlass.', 400, 'INVALID_ANLASS');
            return;
        }

        JsonResponse::send($this->clientApiService->listShooters($anlassId, $sinceId));
    }

    /**
     * Importiert Schussdaten eines Clients fuer einen Anlass.
     */
    public function importShots(array $params): void
    {
        $user = $this->requireApiUser();
        if ($user === null) {
            return;
        }

        $anlassId = (int) ($params['id'] ?? 0);
        $payload = $this->jsonPayload();
        $payloadAnlassId = (int) ($payload['AnlassId'] ?? $payload['anlassId'] ?? 0);
        $shots = $payload['Shots'] ?? $payload['shots'] ?? [];

        if ($anlassId <= 0 || ($payloadAnlassId > 0 && $payloadAnlassId !== $anlassId)) {
            JsonResponse::error('Ungültiger Anlass.', 400, 'INVALID_ANLASS');
            return;
        }

        if (!is_array($shots)) {
            JsonResponse::error('Shots muss ein Array sein.', 400, 'INVALID_INPUT');
            return;
        }

        try {
            $created = $this->clientApiService->importShots($anlassId, $shots, (int) $user['id']);
        } catch (Throwable $exception) {
            JsonResponse::error('Schussdaten konnten nicht importiert werden.', 500, 'IMPORT_FAILED');
            return;
        }

        JsonResponse::send([
            'success' => true,
            'imported' => $created,
            // createMany commits all normalised rows in one transaction.
            // Existing import hashes count as accepted, not newly imported.
            'accepted' => count(array_filter($shots, 'is_array')),
            'duplicates' => count(array_filter($shots, 'is_array')) - $created,
        ], 201);
    }

    /**
     * Validiert den Bearer-Token und liefert den zugehoerigen Benutzer.
     */
    private function requireApiUser(): ?array
    {
        $userId = $this->tokenService->userIdFromAuthorizationHeader($this->authorizationHeader());
        if ($userId === null) {
            JsonResponse::error('Authentifizierung erforderlich.', 401, 'UNAUTHORIZED');
            return null;
        }

        $user = $this->userModel->findById($userId);
        if ($user === null) {
            JsonResponse::error('Authentifizierung erforderlich.', 401, 'UNAUTHORIZED');
            return null;
        }

        return $user;
    }

    /**
     * Liest den JSON-Requestbody als Array.
     */
    private function jsonPayload(): array
    {
        $rawBody = file_get_contents('php://input');
        if ($rawBody === false || trim($rawBody) === '') {
            return [];
        }

        $payload = json_decode($rawBody, true);

        return is_array($payload) ? $payload : [];
    }

    /**
     * Ermittelt den Authorization-Header auch hinter Redirect/FastCGI Setups.
     */
    private function authorizationHeader(): ?string
    {
        if (isset($_SERVER['HTTP_AUTHORIZATION'])) {
            return (string) $_SERVER['HTTP_AUTHORIZATION'];
        }

        if (isset($_SERVER['REDIRECT_HTTP_AUTHORIZATION'])) {
            return (string) $_SERVER['REDIRECT_HTTP_AUTHORIZATION'];
        }

        return null;
    }
}
