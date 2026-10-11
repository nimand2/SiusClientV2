<?php

declare(strict_types=1);

namespace App\Services;

use App\Models\Gaben;
use App\Models\Schussdaten;
use App\Models\Standblatt;

final class AbrechnungsService
{
    public function __construct(
        private readonly Standblatt $standblattModel,
        private readonly Schussdaten $schussdatenModel,
        private readonly Gaben $gabenModel,
    ) {
    }

    /**
     * Baut alle Daten fuer die Abrechnungsansicht eines Standblatts auf.
     */
    public function buildViewData(int $anlassId, int $standblattId): array
    {
        $stiche = $this->standblattModel->findSticheForStandblatt($standblattId);
        $schuesse = $this->schussdatenModel->findByStartNrAndIdAnlass($standblattId, $anlassId);
        $auswertung = $this->buildAuswertung($stiche, $schuesse);
        $regeln = $this->gabenModel->findRegelnForStiche($this->stichIdsFromAuswertung($auswertung));
        $savedAbgaben = $this->gabenModel->findAbgabenForStandblatt($standblattId);
        $defaultSelected = !$this->gabenModel->areAbgabenGeprueft($standblattId);
        $gaben = $this->buildGabenVergleich($auswertung['rows'], $regeln, $savedAbgaben, $defaultSelected);

        return [
            'stiche' => $stiche,
            'schuesse' => $schuesse,
            'auswertung' => $auswertung,
            'gabenVergleich' => $gaben,
            'gabenSummen' => $this->gabenSummen($gaben),
        ];
    }

    /**
     * Filtert gepostete Gaben auf tatsaechlich erreichbare und waehbare Abgaben.
     */
    public function itemsFromPostedGaben(int $anlassId, int $standblattId, array $postedGaben, array $postedAbgegeben = [], array $postedRuecknahmen = []): array
    {
        $viewData = $this->buildViewData($anlassId, $standblattId);
        $items = [];
        foreach ($viewData['gabenVergleich'] as $gruppe) {
            foreach ($gruppe['gaben'] as $gabe) {
                $ruecknahme = !empty($gabe['abgegeben']) && !empty($postedRuecknahmen[$gabe['stich_id']][$gabe['serie_nummer']][$gabe['gaben_id']]);
                if ($ruecknahme && empty($gabe['erreicht'])) {
                    continue;
                }
                $status = $postedAbgegeben[$gabe['stich_id']][$gabe['serie_nummer']] ?? [];
                $items[] = [
                    'stich_id' => $gabe['stich_id'],
                    'serie_nummer' => $gabe['serie_nummer'],
                    'gaben_id' => $gabe['gaben_id'],
                    'abgegeben' => !$ruecknahme && (!empty($gabe['abgegeben']) || (is_array($status) ? !empty($status[$gabe['gaben_id']]) : !empty($status))),
                ];
            }
        }
        return $items;
    }

    /** Summiert Gabenwerte und Geldzahlungen getrennt nach Abgabestatus. */
    public function gabenSummen(array $gruppen): array
    {
        $summen = ['gesamt' => 0, 'abgegeben' => 0, 'offen' => 0, 'geld_gesamt' => 0, 'geld_abgegeben' => 0, 'geld_offen' => 0];
        foreach ($gruppen as $gruppe) {
            foreach ($gruppe['gaben'] as $gabe) {
                $cents = (int) round((float) $gabe['preis'] * 100);
                $status = !empty($gabe['abgegeben']) ? 'abgegeben' : 'offen';
                $summen['gesamt'] += $cents;
                $summen[$status] += $cents;
                if (!empty($gabe['ist_geld'])) {
                    $summen['geld_gesamt'] += $cents;
                    $summen['geld_' . $status] += $cents;
                }
            }
        }
        return array_map(static fn (int $cents): float => $cents / 100, $summen);
    }

    /**
     * Gruppiert Schussdaten nach Stich und berechnet Totalwerte fuer die Abrechnung.
     */
    private function buildAuswertung(array $stiche, array $schuesse): array
    {
        usort($schuesse, [Schussreihenfolge::class, 'compare']);

        $schuesseByExterneNummer = [];
        foreach ($schuesse as $schuss) {
            if ((int) ($schuss['ins_del'] ?? 0) !== 0) {
                continue;
            }

            $externeNummer = $this->externalNumber($schuss['externe_nummer'] ?? null);
            $schuesseByExterneNummer[$externeNummer][] = $schuss;
        }

        $rows = [];
        $usedExterneNummern = [];
        $usedSchussCountsByExterneNummer = [];
        $total = 0.0;

        foreach ($stiche as $stich) {
            $externeNummer = $this->externalNumber($stich['anzeige_id'] ?? null);
            if ($externeNummer !== '') {
                $usedExterneNummern[] = $externeNummer;
            }

            $anzahlStiche = max(1, (int) ($stich['anzahl_stiche'] ?? 1));
            $anzahlSchuss = max(1, (int) ($stich['anzahl_schuss'] ?? 0));
            $stichSchuesse = $externeNummer === '' ? [] : ($schuesseByExterneNummer[$externeNummer] ?? []);

            for ($stichNummer = 0; $stichNummer < $anzahlStiche; $stichNummer++) {
                $rowStich = $stich;
                $rowStich['anzahl_stiche'] = 1;
                $rowStich['serie_nummer'] = $stichNummer + 1;
                $rowSchuesse = array_slice($stichSchuesse, $stichNummer * $anzahlSchuss, $anzahlSchuss);
                $row = $this->buildStichRow($rowStich, $rowSchuesse);
                $rows[] = $row;
                $total += $row['total'];
            }

            if ($externeNummer !== '') {
                $usedSchussCountsByExterneNummer[$externeNummer] = $anzahlStiche * $anzahlSchuss;
            }
        }

        foreach ($schuesseByExterneNummer as $externeNummer => $stichSchuesse) {
            if (in_array((string) $externeNummer, $usedExterneNummern, true)) {
                $stichSchuesse = array_slice($stichSchuesse, $usedSchussCountsByExterneNummer[(string) $externeNummer] ?? 0);
            }

            if ($stichSchuesse === []) {
                continue;
            }

            $row = $this->buildStichRow([
                'name' => $externeNummer === ''
                    ? 'Nicht zugeordneter Stich ohne externe Nummer'
                    : 'Nicht zugeordneter Stich ' . (string) $externeNummer,
                'short_name' => '',
                'anzahl_schuss' => count($stichSchuesse),
                'anzahl_stiche' => 1,
            ], $stichSchuesse);
            $rows[] = $row;
            $total += $row['total'];
        }

        return [
            'rows' => $rows,
            'total' => $total,
            'schussCount' => array_sum(array_map(static fn (array $row): int => count($row['schuesse']), $rows)),
        ];
    }

    /**
     * Erstellt eine auswertbare Zeile fuer einen Stich mit seinen Schuessen.
     */
    private function buildStichRow(array $stich, array $schuesse): array
    {
        $werte = [];
        $total = 0.0;

        foreach ($schuesse as $schuss) {
            $wert = $this->numericValue($schuss['primaerwertung'] ?? null);
            $werte[] = [
                'id' => (int) ($schuss['id'] ?? 0),
                'primaerwertung' => $wert,
                'sekundaerwertung' => $schuss['sekundaerwertung'] ?? null,
                'mouche' => (int) ($schuss['mouche'] ?? 0) === 1,
                'zeit' => $schuss['schuss_zeit'] ?? null,
                'externe_nummer' => $this->externalNumber($schuss['externe_nummer'] ?? null),
            ];
            $total += $wert;
        }

        $anzahlSchuss = (int) ($stich['anzahl_schuss'] ?? 0);
        $anzahlSchuss = $anzahlSchuss > 0 ? $anzahlSchuss : count($werte);

        return [
            'stich_id' => (int) ($stich['id'] ?? 0),
            'serie_nummer' => (int) ($stich['serie_nummer'] ?? 1),
            'bezeichnung' => (string) ($stich['name'] ?? 'Stich'),
            'kurzname' => (string) ($stich['short_name'] ?? ''),
            'externe_nummer' => $this->externalNumber($stich['anzeige_id'] ?? null),
            'preis' => (float) ($stich['preis'] ?? 0),
            'anzahl_schuss' => max(1, $anzahlSchuss),
            'anzahl_stiche' => max(1, (int) ($stich['anzahl_stiche'] ?? 1)),
            'erwartet' => max(0, (int) ($stich['anzahl_schuss'] ?? 0) * max(1, (int) ($stich['anzahl_stiche'] ?? 1))),
            'total' => $total,
            'schuesse' => $werte,
        ];
    }

    /**
     * Vergleicht erreichte Resultate mit Gabenregeln und markiert waehlbare Gaben.
     */
    private function buildGabenVergleich(array $rows, array $regeln, array $savedAbgaben, bool $defaultSelected = false): array
    {
        $saved = [];
        foreach ($savedAbgaben as $abgabe) {
            $saved[(int) $abgabe['stich_id'] . ':' . (int) ($abgabe['serie_nummer'] ?? 1) . ':' . (int) $abgabe['gaben_id']] = $abgabe;
        }

        $regelnByStich = [];
        foreach ($regeln as $regel) {
            $regelnByStich[(int) $regel['stich_id']][] = $regel;
        }

        $gruppen = [];
        foreach ($rows as $row) {
            $stichId = (int) ($row['stich_id'] ?? 0);
            $serieNummer = (int) ($row['serie_nummer'] ?? 1);
            $stichTotal = (float) ($row['total'] ?? 0);
            $abgegeben = false;
            $gaben = [];

            foreach ($regelnByStich[$stichId] ?? [] as $regel) {
                $minWert = $regel['min_wert'] !== null ? (float) $regel['min_wert'] : (float) ($regel['punktwert'] ?? 0);
                $maxWert = $regel['max_wert'] !== null ? (float) $regel['max_wert'] : null;
                $erreicht = $stichTotal >= $minWert && ($maxWert === null || $stichTotal <= $maxWert);
                $key = $stichId . ':' . $serieNummer . ':' . (int) $regel['gaben_id'];
                if (!$erreicht) {
                    continue;
                }
                $abgegeben = $abgegeben || !empty($saved[$key]['abgegeben']);
                $gaben[] = [
                    'stich_id' => $stichId,
                    'serie_nummer' => $serieNummer,
                    'gaben_id' => (int) $regel['gaben_id'],
                    'name' => (string) ($regel['name'] ?? ''),
                    'anzahl' => (int) ($regel['anzahl'] ?? 0),
                    'limit' => $minWert,
                    'max_wert' => $maxWert,
                    'erreicht' => $erreicht,
                    'selected' => true,
                    'preis' => (float) ($regel['preis'] ?? 0),
                    'ist_geld' => stripos((string) ($regel['name'] ?? ''), 'Barauszahlung') !== false,
                    'abgegeben' => !empty($saved[$key]['abgegeben']),
                    'differenz' => $stichTotal - $minWert,
                ];
            }

            if ($gaben === []) {
                continue;
            }
            $gruppen[] = [
                'stich_id' => $stichId,
                'serie_nummer' => $serieNummer,
                'bezeichnung' => (string) ($row['bezeichnung'] ?? 'Stich'),
                'kurzname' => (string) ($row['kurzname'] ?? ''),
                'total' => $stichTotal,
                'gaben' => $gaben,
                'abgegeben' => $abgegeben,
            ];
        }

        $visible = [];
        foreach ($gruppen as $gruppe) {
            foreach ($gruppe['gaben'] as $gabe) {
                $visible[$gabe['stich_id'] . ':' . $gabe['serie_nummer'] . ':' . $gabe['gaben_id']] = true;
            }
        }
        foreach ($saved as $key => $abgabe) {
            if (empty($abgabe['abgegeben']) || isset($visible[$key])) {
                continue;
            }
            $gruppen[] = [
                'stich_id' => (int) $abgabe['stich_id'],
                'serie_nummer' => (int) ($abgabe['serie_nummer'] ?? 1),
                'bezeichnung' => 'Bereits abgegebene Gabe (vor Resultatkorrektur)',
                'total' => 0,
                'abgegeben' => true,
                'gaben' => [[
                    'stich_id' => (int) $abgabe['stich_id'],
                    'serie_nummer' => (int) ($abgabe['serie_nummer'] ?? 1),
                    'gaben_id' => (int) $abgabe['gaben_id'],
                    'name' => (string) $abgabe['name'], 'preis' => (float) $abgabe['preis'],
                    'ist_geld' => stripos((string) $abgabe['name'], 'Barauszahlung') !== false,
                    'anzahl' => (int) $abgabe['anzahl'], 'limit' => (float) $abgabe['punktwert'],
                    'selected' => true, 'erreicht' => false, 'abgegeben' => true,
                ]],
            ];
        }
        return $gruppen;
    }

    /**
     * Ermittelt die Menge aller Gaben, die fuer die gepostete Auswahl erlaubt sind.
     */
    private function buildSelectableAbgaben(array $rows, array $regeln): array
    {
        $gruppen = $this->buildGabenVergleich($rows, $regeln, []);
        $selectable = [];

        foreach ($gruppen as $gruppe) {
            foreach ($gruppe['gaben'] as $gabe) {
                if (empty($gabe['erreicht'])) {
                    continue;
                }

                $selectable[(int) $gabe['stich_id'] . ':' . (int) $gabe['serie_nummer'] . ':' . (int) $gabe['gaben_id']] = true;
            }
        }

        return $selectable;
    }

    /**
     * Extrahiert eindeutige Stich-IDs aus der berechneten Auswertung.
     */
    private function stichIdsFromAuswertung(array $auswertung): array
    {
        return array_values(array_unique(array_map(
            static fn (array $row): int => (int) ($row['stich_id'] ?? 0),
            (array) ($auswertung['rows'] ?? [])
        )));
    }

    /**
     * Normalisiert externe Schussnummern fuer die Anzeige.
     */
    private function externalNumber(mixed $value): string
    {
        if ($value === null) {
            return '';
        }

        return trim((string) $value);
    }

    /**
     * Normalisiert optionale Zahlenwerte aus Import- und Datenbankfeldern.
     */
    private function numericValue(mixed $value): float
    {
        if ($value === null || $value === '') {
            return 0.0;
        }

        return (float) str_replace(',', '.', (string) $value);
    }
}
