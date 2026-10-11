<?php

declare(strict_types=1);

namespace App\Models {
    class Standblatt {
        public function findSticheForStandblatt(int $id): array {
            return [['id'=>1, 'name'=>'Chilbistich', 'anzeige_id'=>901, 'anzahl_schuss'=>1, 'anzahl_stiche'=>2]];
        }
    }
    class Schussdaten {
        public function findByStartNrAndIdAnlass(int $id, int $anlass): array {
            return [['id'=>1,'externe_nummer'=>901,'primaerwertung'=>47], ['id'=>2,'externe_nummer'=>901,'primaerwertung'=>47]];
        }
    }
    class Gaben {
        public static bool $historisch = false;
        public function findRegelnForStiche(array $ids): array {
            return [
                ['stich_id'=>1,'gaben_id'=>1,'name'=>'Barauszahlung','preis'=>12.50,'anzahl'=>100,'min_wert'=>47,'max_wert'=>47],
                ['stich_id'=>1,'gaben_id'=>2,'name'=>'Sachgabe','preis'=>5,'anzahl'=>50,'min_wert'=>45,'max_wert'=>null],
                ['stich_id'=>1,'gaben_id'=>3,'name'=>'Nicht erreicht','preis'=>20,'anzahl'=>10,'min_wert'=>48,'max_wert'=>null],
            ];
        }
        public function findAbgabenForStandblatt(int $id): array {
            if (self::$historisch) return [['stich_id'=>1,'serie_nummer'=>1,'gaben_id'=>9,'abgegeben'=>1,'name'=>'Schokolade','preis'=>2,'anzahl'=>1,'punktwert'=>45]];
            return [
                ['stich_id'=>1,'serie_nummer'=>1,'gaben_id'=>1,'abgegeben'=>1],
                ['stich_id'=>1,'serie_nummer'=>1,'gaben_id'=>2,'abgegeben'=>0],
            ];
        }
        public function areAbgabenGeprueft(int $id): bool { return true; }
    }
}
namespace {
    require dirname(__DIR__).'/app/Services/Schussreihenfolge.php';
    require dirname(__DIR__).'/app/Services/AbrechnungsService.php';
    $service = new \App\Services\AbrechnungsService(new \App\Models\Standblatt(), new \App\Models\Schussdaten(), new \App\Models\Gaben());
    $check = static function(bool $ok, string $message): void { if (!$ok) throw new \RuntimeException($message); };
    $data = $service->buildViewData(1, 1);
    $check(count($data['gabenVergleich'])===2, 'Both series considered');
    foreach ($data['gabenVergleich'] as $group) {
        $check(array_column($group['gaben'],'gaben_id')===[1,2], 'Only achieved awards shown');
    }
    $totals=$data['gabenSummen'];
    $check($totals['gesamt']===35.0 && $totals['abgegeben']===12.5 && $totals['offen']===22.5, 'Partial delivery deducted per award');
    $check($totals['geld_gesamt']===25.0 && $totals['geld_abgegeben']===12.5 && $totals['geld_offen']===12.5, 'Cash excludes goods and previous payout');
    $items=$service->itemsFromPostedGaben(1,1,[],[1=>[1=>[2=>1]]]);
    $check(count($items)===4, 'Awards selected automatically after previous save');
    $check($items[0]['abgegeben'] && $items[1]['abgegeben'] && !$items[2]['abgegeben'], 'Existing delivery retained and confirmation applies to one award');
    $returned=$service->itemsFromPostedGaben(1,1,[],[1=>[1=>[1=>1]]],[1=>[1=>[1=>1]]]);
    $check(!$returned[0]['abgegeben'], 'Explicit return overrides previous and posted delivery');
    $check($returned[2]['abgegeben']===false, 'Other series remains unchanged');
    $returnedGroups=$data['gabenVergleich'];
    $returnedGroups[0]['gaben'][0]['abgegeben']=false;
    $check($service->gabenSummen($returnedGroups)['geld_offen']===25.0, 'Returned cash becomes outstanding again');
    \App\Models\Gaben::$historisch=true;
    $kept=$service->itemsFromPostedGaben(1,1,[]);
    $check(in_array(9,array_column($kept,'gaben_id'),true), 'Historical delivery retained without confirmation');
    $returnedHistory=$service->itemsFromPostedGaben(1,1,[],[],[1=>[1=>[9=>1]]]);
    $check(!in_array(9,array_column($returnedHistory,'gaben_id'),true), 'Returned historical award removed without new entitlement');
    $method=new \ReflectionMethod($service,'buildGabenVergleich');
    $history=$method->invoke($service,[],[],[['stich_id'=>1,'serie_nummer'=>1,'gaben_id'=>1,'abgegeben'=>1,'name'=>'Barauszahlung','preis'=>12.5,'anzahl'=>100,'punktwert'=>47]]);
    $check($service->gabenSummen($history)['geld_offen']===0.0, 'Historical delivery never paid again');
    echo "Gabenabrechnung passed: thresholds, automatic selection, partial delivery, cash totals and correction history.\n";
}
