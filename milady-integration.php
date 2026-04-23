<?php
/**
 * Milady OCR Integration — Add this snippet to fact-form.php or include as a module
 *
 * This polls the OCR service for completed invoice scans and pre-fills the form.
 */

// Config
$OCR_API_URL = 'https://your-vps-ip:8000';
$OCR_API_KEY = 'your-api-key-here';

function ocr_get_pending($id_pdv) {
    global $OCR_API_URL, $OCR_API_KEY;
    $url = $OCR_API_URL . '/jobs/pending?id_pdv=' . (int)$id_pdv;
    $ctx = stream_context_create([
        'http' => [
            'method' => 'GET',
            'header' => "x-api-key: $OCR_API_KEY\r\nAccept: application/json\r\n",
            'timeout' => 5,
        ],
        'ssl' => [
            'verify_peer' => false,  // Use a real cert in production
            'verify_peer_name' => false,
        ],
    ]);
    $res = @file_get_contents($url, false, $ctx);
    if (!$res) return [];
    $data = json_decode($res, true);
    return $data['jobs'] ?? [];
}

// --- In fact-form.php, add this near the top ---
$ocr_jobs = [];
if ($_SESSION['user']['id_pdv']) {
    $ocr_jobs = ocr_get_pending($_SESSION['user']['id_pdv']);
}

// --- In the HTML, add this section above the form ---
?>
<?php if (!empty($ocr_jobs)) { ?>
<div class="panel panel-info">
    <div class="panel-heading">
        <i class="fa fa-magic"></i> Factures scannées en attente (<?= count($ocr_jobs) ?>)
    </div>
    <div class="panel-body">
        <?php foreach ($ocr_jobs as $job) { 
            $ocr = $job['ocr_result'] ?? [];
            $conf = ($ocr['confidence'] ?? 0) * 100;
            $badge = $conf >= 90 ? 'success' : ($conf >= 70 ? 'warning' : 'danger');
        ?>
        <div class="well well-sm" style="cursor:pointer" onclick="prefillOcr(<?= htmlspecialchars(json_encode($ocr)) ?>)">
            <strong><?= htmlspecialchars($ocr['supplier_name'] ?? 'Fournisseur inconnu') ?></strong>
            <span class="label label-<?= $badge ?>"><?= round($conf) ?>% confiance</span><br>
            <small>
                N° <?= htmlspecialchars($ocr['num_fact'] ?? '-') ?> — 
                <?= htmlspecialchars($ocr['date_fact'] ?? '-') ?> — 
                <?= number_format($ocr['total_ht'] ?? 0, 2, ',', ' ') ?> € HT
            </small>
            <?php if (!empty($ocr['warnings'])) { ?>
                <br><small class="text-warning"><i class="fa fa-exclamation-triangle"></i> <?= htmlspecialchars(implode(', ', $ocr['warnings'])) ?></small>
            <?php } ?>
        </div>
        <?php } ?>
    </div>
</div>

<script>
function prefillOcr(data) {
    // Map OCR fields to your form inputs
    document.querySelector('[name="num_fact"]').value = data.num_fact || '';
    document.querySelector('[name="date_fact"]').value = data.date_fact || '';
    document.querySelector('[name="total_ht"]').value = (data.total_ht || '').toString().replace('.', ',');
    
    // Try to select the matched supplier
    var supplierSelect = document.querySelector('[name="id_f"]');
    if (supplierSelect && data.supplier_matched_id) {
        supplierSelect.value = data.supplier_matched_id;
        $(supplierSelect).trigger('change'); // For Select2
    }
    
    // Show a toast
    alert('Formulaire pré-rempli. Vérifiez les données avant de valider.');
}
</script>
<?php } ?>
