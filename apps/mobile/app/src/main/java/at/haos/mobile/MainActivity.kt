package at.haos.mobile

import android.os.Bundle
import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import kotlinx.coroutines.delay
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch

private val navy = Color(0xFF060E20)
private val surface = Color(0xFF10213D)
private val outline = Color(0xFF285579)
private val cyan = Color(0xFF55DFFF)
private val text = Color(0xFFEAF6FF)
private val muted = Color(0xFFAAC0D6)
private val backdrop = Brush.verticalGradient(listOf(Color(0xFF10396B), navy, navy))

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = android.graphics.Color.rgb(6, 14, 32)
        window.navigationBarColor = android.graphics.Color.rgb(6, 14, 32)
        setContent { MobileApp() }
    }
}

private enum class Tab(val label: String) { Home("Home"), Hermes("Hermes"), Desktop("Desktop"), Devices("Geräte") }

@Composable
private fun MobileApp() {
    var tab by remember { mutableStateOf(Tab.Home) }
    var address by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var identity by remember { mutableStateOf<ByteArray?>(null) }
    var serverCa by remember { mutableStateOf<ByteArray?>(null) }
    var session by remember { mutableStateOf<AuthenticatedViewer?>(null) }
    var missions by remember { mutableStateOf<List<Mission>>(emptyList()) }
    var status by remember { mutableStateOf("Nicht verbunden") }
    var busy by remember { mutableStateOf(false) }
    var wakeMac by remember { mutableStateOf("") }
    var wakeBroadcast by remember { mutableStateOf("192.168.1.255") }
    var waking by remember { mutableStateOf(false) }
    var wakeFeedback by remember { mutableStateOf("") }
    var selectedMission by remember { mutableStateOf("") }
    var missionMenuOpen by remember { mutableStateOf(false) }
    var remoteCaptures by remember { mutableStateOf<List<RemoteCapture>>(emptyList()) }
    var remoteStatus by remember { mutableStateOf("Kein freigegebenes Anwendungsfenster.") }

    val context = androidx.compose.ui.platform.LocalContext.current
    val scope = rememberCoroutineScope()
    val clientPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) runCatching { readCredential(context, uri) }
            .onSuccess { identity = it }.onFailure { status = it.message ?: "Zertifikat nicht lesbar." }
    }
    val caPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) runCatching { readCredential(context, uri) }
            .onSuccess { serverCa = it }.onFailure { status = it.message ?: "CA nicht lesbar." }
    }
    fun refresh() {
        val viewer = session ?: return
        busy = true
        scope.launch {
            runCatching { viewer.missions() }
                .onSuccess { missions = it; status = "Sicher verbunden · Nur Lesezugriff" }
                .onFailure { missions = emptyList(); status = it.message ?: "Verbindungsfehler" }
            busy = false
        }
    }
    // Changing the selected mission or client identity invalidates prior screenshots.
    // Only the existing owner-granted, mTLS read-only snapshot endpoint is called.
    LaunchedEffect(session, tab, selectedMission) {
        remoteCaptures = emptyList()
        if (session == null || tab != Tab.Desktop || selectedMission.isBlank()) return@LaunchedEffect
        while (true) {
            val result = runCatching { session!!.applicationSnapshot(selectedMission) }
            result.onSuccess { snapshot ->
                remoteCaptures = snapshot.captures
                remoteStatus = if (!snapshot.active) {
                    "Diese Mission führt derzeit keine freigegebene Anwendung aus."
                } else if (snapshot.captures.isEmpty()) {
                    "Keine aktuelle, freigegebene Aufnahme (maximal 15 Sekunden gültig)."
                } else {
                    "Nur Beobachtung · ${snapshot.captures.size} freigegebene Aufnahme(n)"
                }
            }.onFailure {
                remoteCaptures = emptyList()
                remoteStatus = "Aufnahmen nicht freigegeben oder Verbindung unterbrochen."
            }
            delay(2500)
        }
    }
    LaunchedEffect(missions) {
        if (missions.none { it.id == selectedMission }) {
            selectedMission = missions.firstOrNull()?.id ?: ""
            remoteCaptures = emptyList()
        }
    }
    MaterialTheme(colorScheme = darkColorScheme(primary = cyan, onPrimary = navy,
        background = navy, onBackground = text, surface = surface, onSurface = text)) {
        Scaffold(containerColor = navy, bottomBar = {
            NavigationBar(containerColor = Color(0xFF0A1832)) {
                Tab.entries.forEach { destination ->
                    val icon = when (destination) {
                        Tab.Home -> Icons.Rounded.Home
                        Tab.Hermes -> Icons.Rounded.AutoAwesome
                        Tab.Desktop -> Icons.Rounded.DesktopWindows
                        Tab.Devices -> Icons.Rounded.Devices
                    }
                    NavigationBarItem(selected = tab == destination, onClick = { tab = destination },
                        icon = { Icon(icon, null) }, label = { Text(destination.label) },
                        colors = NavigationBarItemDefaults.colors(selectedIconColor = navy,
                            selectedTextColor = cyan, indicatorColor = cyan,
                            unselectedIconColor = muted, unselectedTextColor = muted))
                }
            }
        }) { inset ->
            Column(Modifier.fillMaxSize().background(backdrop).padding(inset)
                .verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
                verticalArrangement = Arrangement.spacedBy(18.dp)) {
                TopBar()
                when (tab) {
                    Tab.Home -> {
                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("YOUR SYSTEM. EVERYWHERE.", color = cyan, fontSize = 10.sp,
                                fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                            Text("Willkommen zurück.", color = text, fontSize = 29.sp, fontWeight = FontWeight.Bold)
                            Text("Dein Arbeitsplatz und deine Missionen. Privat, direkt und sicher.",
                                color = muted, fontSize = 13.sp)
                        }
                        Panel {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Rounded.Computer, null, Modifier.size(30.dp), tint = cyan)
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text("Herald OS", fontWeight = FontWeight.Bold, fontSize = 18.sp)
                                    Text(status, color = muted, fontSize = 12.sp, maxLines = 3)
                                }
                                Icon(if (session == null) Icons.Rounded.CloudOff else Icons.Rounded.Lock,
                                    null, tint = cyan)
                            }
                            Spacer(Modifier.height(14.dp))
                            Button(onClick = { if (session != null) refresh() else tab = Tab.Devices },
                                enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                                Text(if (session == null) "Gerät verbinden" else "Verbindung prüfen")
                            }
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Feature("Remote Desktop", "Bildschirm & Eingabe", Icons.Rounded.DesktopWindows,
                                Modifier.weight(1f)) { tab = Tab.Desktop }
                            Feature("Hermes AI", "Missionen & Status", Icons.Rounded.AutoAwesome,
                                Modifier.weight(1f)) { tab = Tab.Hermes }
                        }
                        Text("FREIGEGEBENE MISSIONEN", color = cyan, fontSize = 11.sp, letterSpacing = 1.5.sp)
                        MissionList(missions)
                    }
                    Tab.Hermes -> {
                        Heading("Hermes", "Missionen unterwegs verfolgen")
                        MissionList(missions)
                        Info("Aufträge", "Neue Aufgaben über die App sind noch gesperrt. Dafür muss HAOS zuerst eine eigene gerätegebundene Schreibberechtigung bereitstellen.")
                    }
                    Tab.Desktop -> {
                        Heading("Remote-Ansicht", "Explizit freigegebene Anwendungsausschnitte")
                        Panel {
                            Text("Freigegebene Mission auswählen", color = cyan, fontSize = 13.sp,
                                fontWeight = FontWeight.Bold)
                            Box {
                                OutlinedButton(
                                    onClick = { missionMenuOpen = true },
                                    enabled = session != null && missions.isNotEmpty(),
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Text(missions.firstOrNull { it.id == selectedMission }?.let {
                                        "${it.state} · ${it.id.take(13)}…"
                                    } ?: "Keine Mission freigegeben")
                                    Spacer(Modifier.weight(1f))
                                    Icon(Icons.Rounded.ArrowDropDown, null)
                                }
                                DropdownMenu(expanded = missionMenuOpen,
                                    onDismissRequest = { missionMenuOpen = false }) {
                                    missions.forEach { mission ->
                                        DropdownMenuItem(
                                            text = { Text("${mission.state} · ${mission.id.take(16)}…") },
                                            onClick = {
                                                selectedMission = mission.id
                                                missionMenuOpen = false
                                            }
                                        )
                                    }
                                }
                            }
                            Spacer(Modifier.height(8.dp))
                            Text(remoteStatus, color = muted, fontSize = 12.sp)
                            Text("Nur laufende, ausdrücklich geteilte Missions-Anwendungen. " +
                                "Keine vollständige Desktopfreigabe, keine Eingaberechte.",
                                color = muted, fontSize = 11.sp)
                        }
                        if (remoteCaptures.isEmpty()) {
                            Box(Modifier.fillMaxWidth().height(160.dp)
                                .clip(RoundedCornerShape(23.dp))
                                .background(Color(0xFF08162C))
                                .border(1.dp, outline, RoundedCornerShape(23.dp)),
                                contentAlignment = Alignment.Center) {
                                Icon(Icons.Rounded.DesktopWindows, null, Modifier.size(42.dp), tint = muted)
                            }
                        } else {
                            remoteCaptures.forEach { capture ->
                                Panel {
                                    Text(capture.program, color = cyan, fontWeight = FontWeight.Bold)
                                    val image = remember(capture.image) {
                                        BitmapFactory.decodeByteArray(
                                            capture.image, 0, capture.image.size
                                        )?.asImageBitmap()
                                    }
                                    if (image != null) {
                                        Image(bitmap = image,
                                            contentDescription = "Freigegebene Anwendung: ${capture.program}",
                                            modifier = Modifier.fillMaxWidth().heightIn(max = 400.dp),
                                            contentScale = ContentScale.Fit)
                                    }
                                }
                            }
                        }
                        Panel {
                            Text("PC im lokalen WLAN einschalten", fontWeight = FontWeight.Bold,
                                color = cyan, fontSize = 16.sp)
                            Spacer(Modifier.height(8.dp))
                            Text("Wake-on-LAN benötigt aktiviertes WoL im BIOS/Netzwerkadapter und Stromversorgung am PC. " +
                                "Nur im selben LAN; kein Einschalten über mobile Daten oder das Internet.",
                                color = muted, fontSize = 12.sp)
                            Spacer(Modifier.height(12.dp))
                            OutlinedTextField(value = wakeMac, onValueChange = { wakeMac = it },
                                singleLine = true, modifier = Modifier.fillMaxWidth(),
                                label = { Text("Ethernet-MAC des PCs") },
                                placeholder = { Text("02:11:22:33:44:55") })
                            Spacer(Modifier.height(8.dp))
                            OutlinedTextField(value = wakeBroadcast,
                                onValueChange = { wakeBroadcast = it },
                                singleLine = true, modifier = Modifier.fillMaxWidth(),
                                label = { Text("LAN-Broadcast-Adresse") },
                                placeholder = { Text("192.168.1.255") })
                            Spacer(Modifier.height(10.dp))
                            Button(
                                onClick = {
                                    waking = true
                                    wakeFeedback = ""
                                    scope.launch {
                                        runCatching { WakeOnLan.send(wakeMac, wakeBroadcast) }
                                            .onSuccess {
                                                wakeFeedback = "Magic Packet gesendet. Ob der PC gestartet ist, kann die App ohne Host-Verbindung nicht feststellen."
                                            }
                                            .onFailure {
                                                wakeFeedback = it.message ?: "Wake-on-LAN konnte nicht gesendet werden."
                                            }
                                        waking = false
                                    }
                                }, enabled = !waking && wakeMac.isNotBlank(),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Icon(Icons.Rounded.PowerSettingsNew, null)
                                Spacer(Modifier.width(8.dp))
                                Text(if (waking) "Sende..." else "Wake-on-LAN senden")
                            }
                            if (wakeFeedback.isNotBlank()) {
                                Spacer(Modifier.height(8.dp))
                                Text(wakeFeedback, color = muted, fontSize = 12.sp)
                            }
                        }
                        Info("Remote-Fernsteuerung",
                            "Ein authentifizierter Live-Bildschirm und Eingabekanal müssen auf dem Host noch implementiert und getrennt freigegeben werden.")
                    }
                    Tab.Devices -> {
                        Heading("Gerät verbinden", "Eigene Verbindung ohne Fremdkonto")
                        Info("Sicheres Pairing – Testmodus", "Aktuell unterstützt HAOS die Beobachtung freigegebener Missionen per Client-Zertifikat (mTLS). Zertifikate werden in dieser Alpha-Version nur im Arbeitsspeicher gehalten.")
                        OutlinedTextField(value = address, onValueChange = { address = it },
                            modifier = Modifier.fillMaxWidth(), singleLine = true,
                            label = { Text("HAOS HTTPS-Adresse") },
                            placeholder = { Text("https://haos.example.net:8443") })
                        OutlinedButton(onClick = { clientPicker.launch(arrayOf("*/*")) },
                            modifier = Modifier.fillMaxWidth()) {
                            Icon(Icons.Rounded.Key, null); Spacer(Modifier.width(8.dp))
                            Text(if (identity == null) "Clientzertifikat (.p12) auswählen" else "Clientzertifikat geladen")
                        }
                        OutlinedButton(onClick = { caPicker.launch(arrayOf("*/*")) },
                            modifier = Modifier.fillMaxWidth()) {
                            Icon(Icons.Rounded.VerifiedUser, null); Spacer(Modifier.width(8.dp))
                            Text(if (serverCa == null) "Server-CA (.crt) auswählen" else "Server-CA geladen")
                        }
                        OutlinedTextField(value = password, onValueChange = { password = it },
                            modifier = Modifier.fillMaxWidth(), singleLine = true,
                            label = { Text("Zertifikatspasswort") },
                            visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                        Button(modifier = Modifier.fillMaxWidth(),
                            enabled = !busy && identity != null && serverCa != null && address.isNotBlank(),
                            onClick = {
                                busy = true
                                runCatching {
                                    val chars = password.toCharArray()
                                    try { AuthenticatedViewer(EndpointPolicy.parse(address), identity!!, chars, serverCa!!) }
                                    finally { chars.fill('\u0000') }
                                }.onSuccess {
                                    session = it
                                    password = ""
                                    refresh()
                                }.onFailure {
                                    status = it.message ?: "Ungültige TLS-Konfiguration"
                                    busy = false
                                }
                            }) { Text("Sicher verbinden") }
                        Text(status, fontSize = 12.sp, color = muted)
                    }
                }
            }
        }
    }
}

@Composable
private fun TopBar() {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(Color(0xFF14416D)),
            contentAlignment = Alignment.Center) {
            Icon(Icons.Rounded.Hub, null, tint = cyan)
        }
        Spacer(Modifier.width(11.dp))
        Column {
            Text("HAOS", fontWeight = FontWeight.Black, fontSize = 18.sp, letterSpacing = 2.sp)
            Text("MOBILE · DEVELOPMENT", fontSize = 9.sp, letterSpacing = 1.sp, color = cyan)
        }
        Spacer(Modifier.weight(1f))
        Icon(Icons.Rounded.Shield, null, tint = muted)
    }
}

@Composable
private fun Heading(title: String, subtitle: String) {
    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Text(title, fontSize = 27.sp, fontWeight = FontWeight.Bold, color = text)
        Text(subtitle, fontSize = 13.sp, color = muted)
    }
}

@Composable
private fun Panel(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(22.dp))
        .background(Brush.horizontalGradient(listOf(Color(0xFF123A62), surface)))
        .border(1.dp, outline, RoundedCornerShape(22.dp)).padding(17.dp), content = content)
}

@Composable
private fun Info(title: String, message: String) {
    Panel {
        Text(title, color = cyan, fontSize = 15.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(7.dp))
        Text(message, color = muted, fontSize = 12.sp, lineHeight = 19.sp)
    }
}

@Composable
private fun Feature(title: String, subtitle: String, icon: androidx.compose.ui.graphics.vector.ImageVector,
                    modifier: Modifier = Modifier, onClick: () -> Unit) {
    Column(modifier.clip(RoundedCornerShape(20.dp)).background(surface)
        .border(1.dp, outline, RoundedCornerShape(20.dp))
        .clickable(onClick = onClick).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Icon(icon, null, Modifier.size(29.dp), tint = cyan)
        Text(title, color = text, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        Text(subtitle, color = muted, fontSize = 11.sp, minLines = 2)
    }
}

@Composable
private fun MissionList(rows: List<Mission>) {
    if (rows.isEmpty()) {
        Info("Noch keine freigegebenen Missionen",
            "Verbinde ein autorisiertes HAOS-Gerät. Du siehst nur Missionen, die der Administrator ausdrücklich für dein Zertifikat freigegeben hat.")
    } else {
        rows.forEach { mission ->
            Panel {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Rounded.TaskAlt, null, tint = cyan)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(mission.id, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            color = text, fontSize = 12.sp)
                        Text(mission.state, color = muted, fontSize = 11.sp)
                    }
                }
            }
        }
    }
}
