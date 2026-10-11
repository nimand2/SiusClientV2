<?php

declare(strict_types=1);

namespace App\Services;

final class Schussreihenfolge
{
    /**
     * Empfangs-ID ist nur der letzte Tie-Breaker. Nachgelieferte SIUS-Schuesse
     * muessen an ihrer zeitlichen Position in die Serie eingeordnet werden.
     * Match/Stich-Zaehler koennen zwischen Serien wieder bei 1 beginnen.
     */
    public static function compare(array $left, array $right): int
    {
        return self::key($left) <=> self::key($right);
    }

    private static function key(array $shot): array
    {
        return [
            (string) ($shot['schuss_zeit'] ?? $shot['created_at'] ?? ''),
            (int) ($shot['zeit_seit_jahresanfang'] ?? 0),
            (int) ($shot['log_event'] ?? 0),
            (int) ($shot['id'] ?? 0),
        ];
    }
}
