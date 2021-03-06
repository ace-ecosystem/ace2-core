# Events

Every significant event that the core does can be subscribed to. Subscribers receive notifications when events are fired. Events are triggered by specific conditions.

## Available Events

<table>
<tr>
    <th><b>Event</b></th>
    <th><b>Args</b></th>
    <th><b>Description</b></th>
</tr>
<tr>
    <td colspan="3"><b>Root Analysis Events</b></td>
</tr>
<tr>
    <td><code>/core/analysis/root/new</code></td>
    <td><code>root:RootAnalysis</code></td>
    <td>A new root added.</td>
</tr>
<tr>
    <td><code>/core/analysis/root/modified</code></td>
    <td><code>root:RootAnalysis</code></td>
    <td>Root analysis updated.</td>
</tr>
<tr>
    <td><code>/core/analysis/root/deleted</code></td>
    <td><code>root_uuid:str</code></td>
    <td>Root analysis deleted.</td>
</tr>
<tr>
    <td colspan="3"><b>Analysis Detail Events</b></td>
</tr>
<tr>
    <td><code>/core/analysis/details/new</code></td>
    <td><code>root:RootAnalysis<br>uuid:str</code></td>
    <td>Analysis detail added.</td>
</tr>
<tr>
    <td><code>/core/analysis/details/modified</code></td>
    <td><code>root:RootAnalysis<br>uuid:str</code></td>
    <td>Analysis detail updated.</td>
</tr>
<tr>
    <td><code>/core/analysis/details/deleted</code></td>
    <td><code>uuid:str</code></td>
    <td>Analysis detail deleted.</td>
</tr>
<tr>
    <td colspan="3"><b>Alert Events</b></td>
</tr>
<tr>
    <td><code>/core/alert</code></td>
    <td><code>root:RootAnalysis</code></td>
    <td>Root sent to alert management system.</td>
</tr>
<tr>
    <td colspan="3"><b>Analysis Module Tracking Events</b></td>
</tr>
<tr>
    <td><code>/core/module/new</code></td>
    <td><code>amt:AnalysisModuleType</code></td>
    <td>New analysis module type added.</td>
</tr>
<tr>
    <td><code>/core/module/modified</code></td>
    <td><code>amt:AnalysisModuleType</code></td>
    <td>Existing analysis module type version updated.</td>
</tr>
<tr>
    <td><code>/core/module/deleted</code></td>
    <td><code>amt:AnalysisModuleType</code></td>
    <td>Analysis module type removed.</td>
</tr>
<tr>
    <td colspan="3"><b>Analysis Request Tracking Events</b></td>
</tr>
<tr>
    <td><code>/core/request/new</code></td>
    <td><code>request:AnalysisRequest</code></td>
    <td>New request tracked.</td>
</tr>
<tr>
    <td><code>/core/request/deleted</code></td>
    <td><code>request_uuid:str</code></td>
    <td>Request deleted.</td>
</tr>
<tr>
    <td><code>/core/request/expired</code></td>
    <td><code>request:AnalysisRequest</code></td>
    <td>Request expired.</td>
</tr>
<tr>
    <td colspan="3"><b>Cache Tracking Events</b></td>
</tr>
<tr>
    <td><code>/core/cache/new</code></td>
    <td><code>cache_key:str<br>
    request:AnalysisRequest</code></td>
    <td>Analysis request result cached.</td>
</tr>
<tr>
    <td colspan="3"><b>Config Events</b></td>
</tr>
<tr>
    <td><code>/core/config/set</code></td>
    <td><code>key:str<br>
    value:Any</code></td>
    <td>Configuration value set.</td>
</tr>
<tr>
    <td colspan="3"><b>Storage Events</b></td>
</tr>
<tr>
    <td><code>/core/storage/new</code></td>
    <td><code>sha256:str<br>
    meta:ContentMetadata</code></td>
    <td>Content stored.</td>
</tr>
<tr>
    <td><code>/core/storage/deleted</code></td>
    <td><code>sha256:str</code></td>
    <td>Content deleted.</td>
</tr>
<tr>
    <td colspan="3"><b>Work Queue Events</b></td>
</tr>
<tr>
    <td><code>/core/work/queue/new</code></td>
    <td><code>amt:str</td>
    <td>New work queue created.</td>
</tr>
<tr>
    <td><code>/core/work/queue/deleted</code></td>
    <td><code>amt:str</td>
    <td>Work queue deleted.</td>
</tr>
<tr>
    <td><code>/core/work/add</code></td>
    <td><code>amt:str<br>
    request:AnalysisRequest</td>
    <td>Work assigned to queue.</td>
</tr>
<tr>
    <td><code>/core/work/remove</code></td>
    <td><code>amt:str<br>
    request:AnalysisRequest</td>
    <td>Removed work previously assigned to queue.</td>
</tr>
<tr>
    <td colspan="3"><b>Processing Events</b></td>
</tr>
<tr>
    <td><code>/core/analysis/root/expired</code></td>
    <td><code>root:RootAnalysis</td>
    <td>Root expired after processing.</td>
</tr>
<tr>
    <td><code>/core/cache/hit</code></td>
    <td><code>root:RootAnalysis<br>
    observable:Observable<br>
    ar:AnalysisRequest</td>
    <td>Cache results used for analysis.</td>
</tr>
<tr>
    <td><code>/core/work/assigned</code></td>
    <td><code>ar:AnalysisRequest</td>
    <td>Analysis request assigned to module instance.</td>
</tr>
<tr>
    <td><code>/core/processing/request/observable</code></td>
    <td><code>ar:AnalysisRequest</td>
    <td>Analysis request created for observable and analysis module type.</td>
</tr>
<tr>
    <td><code>/core/processing/request/root</code></td>
    <td><code>ar:AnalysisRequest</td>
    <td>Received request to analyze root.</td>
</tr>
<tr>
    <td><code>/core/processing/request/result</code></td>
    <td><code>ar:AnalysisRequest</td>
    <td>Received request to process analysis result.</td>
</tr>
</table>