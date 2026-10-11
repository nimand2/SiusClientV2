<?php

declare(strict_types=1);

namespace App\Models {
    class Stich {
        public function findByAnlassId(int $id): array {
            return [['id'=>4, 'name'=>'Finalstich', 'anzeige_id'=>1, 'anzahl_schuss'=>1]];
        }
    }
    class Standblatt {
        public function findForAnlassWithAdresse(int $id): array {
            $rows=[];
            for ($i=1; $i<=14; $i++) {
                $rows[]=['id'=>$i, 'id_adresse'=>$i+100, 'id_anlass'=>$id, 'vorname'=>'Test', 'nachname'=>'Person '.$i, 'geburtsdatum'=>$i<=7?'1970-01-01':'2009-12-31', 'final_teilnahme'=>in_array($i,[1,6,7,8,13,14],true)?1:0, 'datum'=>'2026-10-09', 'lizenz'=>'L'.$i, 'passwort'=>'must-not-export'];
            }
            return $rows;
        }
    }
    class Schussdaten {
        public function findByAnlassId(int $id): array {
            $rows=[];
            for ($i=1; $i<=14; $i++) $rows[]=['start_nr'=>$i, 'externe_nummer'=>1, 'primaerwertung'=>100-$i];
            return $rows;
        }
    }
}
namespace {
    require dirname(__DIR__).'/app/Services/Schussreihenfolge.php';
    require dirname(__DIR__).'/app/Services/RanglistenService.php';
    require dirname(__DIR__).'/app/Services/FinalService.php';
    require dirname(__DIR__).'/app/Core/Url.php';
    require dirname(__DIR__).'/app/Core/Navigation.php';
    require dirname(__DIR__).'/app/Core/View.php';
    define('APP_BASE_PATH','');
    $check=static function(bool $ok,string $message): void { if (!$ok) throw new \RuntimeException($message); };
    $standblattModel=new \App\Models\Standblatt();
    $service=new \App\Services\FinalService(new \App\Services\RanglistenService(new \App\Models\Stich(),$standblattModel,new \App\Models\Schussdaten()),$standblattModel);
    $anlass=['id'=>1,'name_anlass'=>'Testanlass','start_anlass'=>'2026-10-09','final_stich_id'=>4,'final_anzahl_u18'=>6,'final_anzahl_ue18'=>6];
    $final=$service->buildForAnlass($anlass);
    $check(array_column($final['teilnehmer'],'standblatt_id')===[8,13,14,1,6,7],'Only qualified entrants with participation wish');
    $check(count($final['kategorien']['u18']['qualifizierte'])===7,'Scan U18 ranking when insufficient confirmations');
    $check(count($final['kategorien']['ue18']['qualifizierte'])===7,'Scan Ü18 ranking when insufficient confirmations');
    $limited=$anlass;
    $limited['final_anzahl_u18']=2;
    $limited['final_anzahl_ue18']=2;
    $check(array_column($service->buildForAnlass($limited)['teilnehmer'],'standblatt_id')===[8,13,1,6],'Fill each category to exact limit with confirmed entrants');
    $ranking=new \App\Services\RanglistenService(new \App\Models\Stich(),$standblattModel,new \App\Models\Schussdaten());
    $check($ranking->finalStatusForStandblatt(1,7,$anlass)['qualifiziert'],'Replacement shown qualified in billing');
    $check(!$ranking->finalStatusForStandblatt(1,7,$limited)['qualifiziert'],'No replacement after category is full');
    $export=$service->exportData($anlass,$final,'u18');
    $json=json_encode($export,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE);
    $check(!str_contains($json,'must-not-export')&&!str_contains($json,'passwort'),'Export whitelist');
    $check($export['teilnehmer_anzahl']===3,'Export count');
    foreach($export['teilnehmer'] as $row) {
        $barcode=(int)$row['barcode'];
        $check($barcode%97===0,'SIUS checksum');
        $check(intdiv($barcode,100)-10000000===$row['standblatt_nummer'],'Barcode start number');
        $check($row['start_nummer']===$row['standblatt_nummer'],'Stable start number');
    }
    $check(array_column($export['teilnehmer'],'standblatt_nummer')===[8,13,14],'U18 export isolated');
    $adultExport=$service->exportData($anlass,$final,'ue18');
    $check(array_column($adultExport['teilnehmer'],'standblatt_nummer')===[1,6,7],'Ü18 export isolated');
    $check($export['final']['id']!==$adultExport['final']['id'],'Independent final identifiers');
    $final=$service->forCategory($final,'u18');
    $blaetter=[];
    foreach ($final['teilnehmer'] as $row) $blaetter[]=['anlass'=>$anlass,'standblatt'=>$row['standblatt'],'adresse'=>$row['standblatt'],'stiche'=>[['name'=>'Finalstich','anzahl_schuss'=>5,'anzahl_stiche'=>1]],'gaben'=>[],'batchPrint'=>true];
    ob_start();\App\Core\View::render('anlass/finalPrint',['anlass'=>$anlass,'final'=>$final,'blaetter'=>$blaetter]);$html=ob_get_clean();
    $check(substr_count($html,'<!DOCTYPE html>')===1,'Single bulk print document');
    $check(substr_count($html,'<main class="sheet">')===3,'Exactly one sheet per entrant');
    $check(substr_count($html,'class="barcode-svg"')===3,'Barcode on every sheet');
    foreach($export['teilnehmer'] as $row) $check(str_contains($html,$row['barcode']),'Print and export same barcode');
    $check(str_contains($html,'.sheet + .sheet'),'Break only before subsequent sheets');
    $check(!str_contains($html, "window.addEventListener('load'"), 'Final printing stays manual');
    ob_start();\App\Core\View::render('loesen/standblattPrint',array_replace($blaetter[0],['batchPrint'=>false]));$single=ob_get_clean();
    $check(substr_count($single,'<!DOCTYPE html>')===1&&str_contains($single,'class="screen-actions"'),'Original single-sheet printing');
    $check(str_contains($single, "window.addEventListener('load'"), 'Single standblatt opens print dialog automatically');
    $anlass['final_anzahl_u18']=0;
    $check(array_column($service->buildForAnlass($anlass)['teilnehmer'],'standblatt_id')===[1,6,7],'Per-category zero places');
    $anlass['final_stich_id']=null;
    $check($service->buildForAnlass($anlass)['teilnehmer']===[],'Final disabled');
    echo "Final tests passed: qualification, wishes, category limits, export fields, barcode parity, bulk and single printing.\n";
}
