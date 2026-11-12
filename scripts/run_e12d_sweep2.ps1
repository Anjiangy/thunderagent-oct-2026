$pA='31475'; $pB='32425'; $host_='<ASCEND-HOST>'
$out='E:\studyfiles\dsh\Thunderagent\program-executor\data\e12d_sweep.csv'
"arm,programs,prefix_words,rep,wall_s,dq_a,dh_a,dq_b,dh_b,hit_cluster,tok_per_s,notes" | Set-Content -LiteralPath $out -Encoding UTF8
function Get-Met($port,$url) {
  $raw = ssh -o BatchMode=yes -p $port root@<ASCEND-HOST> ("curl -s --max-time 6 " + $url) 2>&1
  $q=0.0;$h=0.0
  foreach ($ln in ($raw -split "`n")) {
    if ($ln -match '^vllm:prefix_cache_queries_total') { $q += [double](($ln -split '\s+')[-1]) }
    elseif ($ln -match '^vllm:prefix_cache_hits_total') { $h += [double](($ln -split '\s+')[-1]) }
  }
  @($q,$h)
}
$jobs = @(
 @{n='ta';   cfg='cfg_c32_ta.yaml';   sl='0:32'; progs=32; words=5000; reps=3},
 @{n='like'; cfg='cfg_c32_like.yaml'; sl='0:32'; progs=32; words=5000; reps=3},
 @{n='ta';   cfg='cfg_c16_ta.yaml';   sl='0:16'; progs=16; words=8000; reps=2},
 @{n='like'; cfg='cfg_c16_like.yaml'; sl='0:16'; progs=16; words=8000; reps=2}
)
foreach ($it in $jobs) {
  for ($r=1; $r -le $it.reps; $r++) {
    $ra = ssh -o BatchMode=yes -p $pA root@<ASCEND-HOST> 'bash /root/e5/engine.sh' 2>&1 | Select-Object -Last 1
    $rb = ssh -o BatchMode=yes -p $pB root@<ASCEND-HOST> 'bash /root/e5/engine.sh' 2>&1 | Select-Object -Last 1
    "ENGINES arm=$($it.n) rep=$r A=$ra B=$rb"
    $up = ssh -o BatchMode=yes -p $pA root@<ASCEND-HOST> ("bash /root/e5/arm.sh " + $it.n) 2>&1 | Select-Object -Last 1
    "ROUTER $up"
    $a0 = Get-Met $pA 'http://127.0.0.1:8110/metrics'; $b0 = Get-Met $pB 'http://127.0.0.1:8110/metrics'
    $t0 = Get-Date
    $res = ssh -o BatchMode=yes -p 50034 agent-bench@<TM4> ("bash /home/agent-bench/r_arm.sh src/minisweagent/config/extra/" + $it.cfg + " " + $it.sl) 2>&1 | Select-Object -Last 1
    $wall = [int]((Get-Date) - $t0).TotalSeconds
    $a1 = Get-Met $pA 'http://127.0.0.1:8110/metrics'; $b1 = Get-Met $pB 'http://127.0.0.1:8110/metrics'
    $dqa=$a1[0]-$a0[0]; $dha=$a1[1]-$a0[1]; $dqb=$b1[0]-$b0[0]; $dhb=$b1[1]-$b0[1]
    $tq=$dqa+$dqb; $th=$dha+$dhb
    $hit=[math]::Round(100*$th/[math]::Max($tq,1),2); $tps=[math]::Round($tq/[math]::Max($wall,1),1)
    $note = ("$res" -replace ',',';')
    "$($it.n),$($it.progs),$($it.words),$r,$wall,$([int]$dqa),$([int]$dha),$([int]$dqb),$([int]$dhb),$hit,$tps,$note" | Add-Content -LiteralPath $out
    "DONE arm=$($it.n) progs=$($it.progs) rep=$r wall=${wall}s hit=$hit tps=$tps"
  }
}
'SWEEP_COMPLETE'
