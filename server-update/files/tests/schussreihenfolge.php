<?php

declare(strict_types=1);

require dirname(__DIR__) . '/app/Services/Schussreihenfolge.php';

$shots = [
    ['id' => 1, 'schuss_zeit' => '2026-10-11 10:00:03', 'log_event' => '100'],
    ['id' => 90, 'schuss_zeit' => '2026-10-11 10:00:01', 'log_event' => '98'],
    ['id' => 92, 'schuss_zeit' => '2026-10-11 10:00:02', 'log_event' => '99'],
];
usort($shots, [App\Services\Schussreihenfolge::class, 'compare']);
if (array_column($shots, 'id') !== [90, 92, 1]) {
    throw new RuntimeException('Nachgelieferte Schuesse sind nicht chronologisch.');
}
$sameTime = [
    ['id' => 1, 'schuss_zeit' => '2026-10-11 10:00:01', 'log_event' => '10'],
    ['id' => 2, 'schuss_zeit' => '2026-10-11 10:00:01', 'log_event' => '2'],
];
usort($sameTime, [App\Services\Schussreihenfolge::class, 'compare']);
if (array_column($sameTime, 'log_event') !== ['2', '10']) {
    throw new RuntimeException('LogEvent muss numerisch sortiert werden.');
}
$manual = [['id' => 5], ['id' => 2]];
usort($manual, [App\Services\Schussreihenfolge::class, 'compare']);
if (array_column($manual, 'id') !== [2, 5]) {
    throw new RuntimeException('Fallback fuer alte/manuelle Datensaetze fehlt.');
}
echo "Schussreihenfolge: Nachlieferung, numerische Ereignisse und Fallback bestanden.\n";
