# Plan de arquitectura: de app local a servicio con cifrado de extremo a extremo

Objetivos definidos: usar la app en el celular, sincronizar varios dispositivos, conectar bancos
automáticamente y venderla como servicio — **sin que el servidor pueda leer los datos financieros**
(cifrado de extremo a extremo, E2EE).

## 0. Qué prometer (y qué no)

"100% seguro" no es una promesa que se pueda cumplir ni defender: ningún sistema lo es, y en Chile
una afirmación publicitaria falsa expone a la Ley del Consumidor y, desde diciembre de 2026, a la Ley
21.719 de datos personales. Promesas concretas y verificables que esta arquitectura sí permite:

- "Tus datos financieros se cifran en tu dispositivo. Nosotros guardamos solo datos ilegibles."
- "Ni nuestro equipo ni un atacante que robe nuestros servidores puede leer tus movimientos."
- "Cifrado AES-256 con una clave que sale de tu contraseña. Auditado por terceros." (cuando lo esté)

## 1. Punto de partida (ya implementado)

`src/boveda.py` cifra la base completa con un esquema pensado para crecer a la nube:

| Pieza | Hoy | Por qué sirve para la nube |
|---|---|---|
| Clave de datos (DEK) aleatoria, AES-256-GCM | ✅ | La misma DEK se comparte entre dispositivos sin re-cifrar datos |
| DEK envuelta por contraseña (scrypt) y por código de recuperación | ✅ | Un dispositivo nuevo solo necesita la DEK envuelta (que el servidor puede guardar sin leerla) |
| Cabecera autenticada, escritura atómica | ✅ | Detecta manipulación del archivo en tránsito o en el servidor |
| Formato estándar (AES-GCM + scrypt, JSON) | ✅ | Se implementa igual en JavaScript (WebCrypto + scrypt-js), Kotlin o Swift |

## 2. Arquitectura propuesta

```
 Dispositivos (PC, celular)                         Servidor (nunca ve datos en claro)
 ┌──────────────────────────────┐                  ┌──────────────────────────────────────┐
 │ App cliente                  │  HTTPS (TLS 1.3) │ Servicio de identidad                │
 │  - Inicio de sesión (§3)     │ ───────────────▶ │  - Cuentas, sesiones, 2FA/passkeys   │
 │  - Licencia firmada (§3.5)   │                  │  - Dispositivos autorizados          │
 │  - SQLite local descifrado   │                  ├──────────────────────────────────────┤
 │    solo en memoria           │ ◀─────────────── │ Servicio de suscripción              │
 │  - Cifra/descifra con la DEK │                  │  - Planes, pagos (webhooks), licencia│
 │  - Parsers, análisis, UI     │                  ├──────────────────────────────────────┤
 └──────────────────────────────┘                  │ Servicio de datos                    │
                                                   │  - Blobs/eventos CIFRADOS            │
                                                   │  - DEK envueltas (ilegibles)         │
                                                   │  - Relay de bancos (ver §5)          │
                                                   └──────────────────────────────────────┘
```

Identidad y suscripción guardan datos **legibles** (email, plan, estado de pago) porque son
necesarios para cobrar; van en una base separada de los datos financieros, que solo existen cifrados.

**Principio:** toda la lógica que toca datos (parsers de cartola, categorización, proyecciones) corre
en el dispositivo. El servidor solo guarda, sincroniza y cobra.

## 3. Inicio de sesión, cuentas y suscripción

Con suscripción, cada usuario necesita una cuenta. La regla de diseño: **una sola contraseña
("contraseña maestra") sirve para iniciar sesión y para descifrar**, pero el servidor nunca recibe
nada que le permita descifrar (mismo modelo que Bitwarden/1Password). La contraseña de la bóveda local
actual pasa a ser esa contraseña maestra al crear la cuenta.

### 3.1 Derivación de claves (en el dispositivo)

1. `clave_maestra = scrypt(contraseña, sal_de_la_cuenta)` — **nunca sale del dispositivo**.
2. De ella se derivan con HKDF dos claves independientes:
   - `clave_cifrado` → envuelve la DEK (como hace hoy `boveda.py`).
   - `clave_auth` → se envía al servidor, que guarda solo `hash(clave_auth)` con su propia sal
     (Argon2id). Filtrar la base de cuentas no permite descifrar datos ni probar contraseñas a bajo costo.
3. Evolución recomendada: protocolo **OPAQUE** (el servidor no ve ni siquiera `clave_auth`).

### 3.2 Flujos

| Flujo | Qué pasa |
|---|---|
| **Registro** | Email + contraseña maestra → el dispositivo genera DEK, par X25519 y código de recuperación; sube `hash(clave_auth)`, DEK envuelta dos veces y clave pública. Verificación de email por enlace. |
| **Inicio de sesión** | El dispositivo pide la sal de la cuenta, deriva `clave_auth`, el servidor la verifica y entrega un token de sesión + la DEK envuelta; el dispositivo la desenvuelve localmente. |
| **2FA** | TOTP o passkeys (WebAuthn) como segundo factor del login. Obligatorio para planes pagados. |
| **Nuevo dispositivo** | Login normal + aprobación desde un dispositivo ya autorizado o 2FA. Lista de dispositivos visible y revocable por el usuario. |
| **Desbloqueo diario** | En el mismo dispositivo: PIN corto o biometría (Face ID/huella) que libera una copia de la DEK guardada en el llavero seguro del sistema (Keychain, Android Keystore, Windows Hello/DPAPI). |
| **Olvidé mi contraseña** | ⚠️ Con E2EE el servidor **no puede** recuperar los datos. Solo con el código de recuperación se re-envuelve la DEK con una contraseña nueva. Sin código: se puede recuperar la *cuenta* (email) y la suscripción, pero los datos se pierden. Esto debe explicarse claramente al registrarse. |
| **Cambio de contraseña** | Re-envuelve la DEK y reemplaza `hash(clave_auth)`; cierra las demás sesiones. |
| **Eliminar cuenta** | Borra blobs cifrados, DEK envueltas y datos de cuenta; conserva solo lo que la ley tributaria exija sobre pagos. |

### 3.3 Sesiones

- Token de acceso de vida corta (~15 min) + token de refresco rotativo por dispositivo, revocable.
- En el escritorio, los tokens se guardan en el llavero del sistema operativo, no en archivos planos.
- Límite de intentos por cuenta e IP, avisos por email ante inicio de sesión desde un dispositivo nuevo.

### 3.4 Suscripción

- Estados: `prueba` → `activa` → `vencida` / `cancelada`. Los cambios los dispara el procesador de
  pagos vía webhook verificado (firma), nunca el cliente.
- El servicio de suscripción es la única fuente de verdad del plan de cada cuenta.

### 3.5 Licencia en el dispositivo

- Al iniciar sesión o renovar, el servidor entrega una **licencia firmada** (Ed25519) con cuenta, plan
  y fecha de expiración. La app la verifica con la clave pública incluida en la app, sin internet.
- Período de gracia offline (p. ej. 14 días) para quien no tenga conexión.
- **Suscripción vencida = modo solo lectura, nunca bloqueo de datos**: el usuario siempre puede abrir,
  ver y exportar su información (son sus datos; bloquearlos sería un problema legal y de confianza).
  Lo que se desactiva es lo de pago: sincronización, conexión con bancos, funciones premium.
- La licencia no reemplaza la seguridad del servidor: todo lo premium que ocurra en el servidor
  (sincronización, bancos) valida la suscripción del lado servidor.

## 4. Sincronización

- **Fase 1 — blob completo (simple, suficiente para 1 persona con 2–3 dispositivos):** se sube el
  archivo cifrado entero con un número de versión. Si el servidor tiene una versión más nueva que la
  que el dispositivo editó, se avisa del conflicto en vez de pisar datos. Es lo que ya produce
  `boveda.guardar()`.
- **Fase 2 — registro de cambios cifrado:** cada cambio (transacción nueva, categoría editada) se sube
  como un evento cifrado individual; los dispositivos los aplican en orden. Permite editar desde dos
  dispositivos a la vez y reduce el tráfico. Requiere IDs globales (UUID) en vez de autoincrementales.

## 5. Conexión con bancos (el punto delicado del E2EE)

Los agregadores (Fintoc y similares) exigen una clave secreta que **solo puede vivir en un servidor**,
así que los movimientos pasan por el servidor antes de llegar al dispositivo. Para mantener el E2EE:

- Cada usuario tiene un par de claves X25519. La pública se guarda en el servidor; la privada, dentro
  de su bóveda.
- El servidor recibe los movimientos del agregador, los **cifra de inmediato con la clave pública del
  usuario** ("sealed box") y descarta el texto en claro. Solo el dispositivo del usuario puede abrirlos.
- Honestidad obligatoria: durante esos milisegundos el servidor sí ve los datos. La promesa correcta
  para esta función es "no almacenamos tus movimientos en forma legible", no "nunca los vemos". Debe
  ser opcional y explicado al activarla; quien no la active mantiene E2EE total con carga de PDFs.
- Finanzas Abiertas (vigencia julio 2027): consumir las APIs de los bancos directamente exige
  inscribirse como PSBI ante la CMF (sociedad chilena, políticas de seguridad y datos, certificado de
  seguridad de interfaces y pruebas funcionales por terceros — ver NCG 514/569). Recomendación: partir
  con un agregador ya inscrito y evaluar la inscripción propia solo si el volumen lo justifica.

## 6. Celular

La app actual es Python + NiceGUI y no corre nativa en un teléfono. Opciones:

| Opción | Pros | Contras |
|---|---|---|
| **PWA** (web instalable): SQLite en WASM + WebCrypto | Un solo código para PC y celular; E2EE viable (cifra en el navegador) | Hay que portar parsers y análisis de Python a TypeScript (o usar Pyodide, pesado); scrypt no está en WebCrypto (usar librería) |
| App nativa (Flutter / React Native) | Mejor experiencia, biometría (Face ID/huella) para desbloquear | Segundo código a mantener; tiendas cobran 15–30% de suscripciones compradas dentro de la app |
| Web servida por el servidor (NiceGUI en la nube) | Reutiliza todo el código actual | **Rompe el E2EE**: el servidor descifraría los datos para pintarlos. No recomendado |

**Recomendación:** PWA como primer paso para el celular (consulta y registro rápido), manteniendo la
carga de PDFs en el escritorio al principio; evaluar nativa cuando haya usuarios pagando.

## 7. Pagos y suscripción

- Procesadores con presencia en Chile: Flow, Mercado Pago, Transbank; verificar disponibilidad y
  costos de procesadores internacionales antes de elegir.
- Vender la suscripción por la web (no dentro de la app del celular) evita la comisión de las tiendas.
- Datos de cuenta y pago (email, plan) **no** van cifrados E2EE: son necesarios para cobrar. Van en
  una base separada de los blobs cifrados y cubiertos por la política de privacidad.

## 8. Hosting

- Como los datos llegan cifrados, la ubicación del servidor no expone su contenido; aun así, un
  proveedor con región en Santiago (p. ej. Google Cloud `southamerica-west1`) mejora latencia y
  simplifica conversaciones de cumplimiento.
- Blobs en almacenamiento de objetos con versionado; API pequeña (FastAPI encaja con el stack Python
  actual); base de datos administrada para cuentas y suscripciones.

## 9. Programa de seguridad (lo que respalda la promesa)

Checklist de revisiones por etapa. Cada etapa se cierra recién cuando sus casillas están marcadas.

### 9.0 Base (sin servidor)
- [x] Base de datos cifrada, sesión atada al navegador, bloqueo por inactividad, cabeceras de seguridad
- [x] Actualizaciones firmadas (Ed25519) con clave fuera de GitHub; releases en borrador hasta firmarlos
- [x] Auditoría de dependencias (`pip-audit`) sin vulnerabilidades conocidas en `requirements-dev.txt`
- [x] Escaneo de secretos y bloqueo de push con secretos; alertas y PRs de seguridad de Dependabot
- [x] Protección de `master`: cambios solo vía PR, sin force-push ni borrado
- [ ] 2FA en la cuenta de GitHub del mantenedor (y de cualquier colaborador)
- [ ] Licencia del repositorio definida (hoy público y sin licencia) antes de vender
- [ ] Firma de código de Windows del instalador (certificado pagado; elimina la advertencia de SmartScreen)

### 9.1 Diseño, antes de escribir el servidor
- [ ] Modelo de amenazas escrito (flujos de datos, quién ataca cada punto, qué pasa si falla cada pieza;
      incluye lo que el E2EE NO protege, como un dispositivo con malware)
- [ ] Revisión externa del diseño criptográfico: jerarquía de claves, separación `clave_auth`/`clave_cifrado`,
      recuperación, alta de dispositivos nuevos

### 9.2 Servidor y API (OWASP API Security Top 10, OWASP ASVS nivel 2)
- [ ] Autorización por objeto (BOLA/IDOR): ningún usuario accede a blobs, dispositivos o suscripción de otro
      cambiando un ID — pruebas automáticas por endpoint
- [ ] Autenticación: freno a fuerza bruta y credential stuffing, 2FA sin atajos, rotación y revocación de
      tokens, sin errores típicos de JWT (algoritmo `none`, confusión de claves)
- [ ] Límites de consumo: tamaño máximo de blobs y peticiones por minuto por cuenta e IP
- [ ] Webhooks de pagos: firma verificada, rechazo de reenvíos (marca de tiempo) e idempotencia
- [ ] Secretos en un gestor de secretos con rotación; `gitleaks` en CI
- [ ] Infraestructura: base de datos no expuesta a internet, IAM de mínimo privilegio, respaldos cifrados con
      restauración probada
- [ ] Logs sin datos financieros, tokens ni contraseñas; alertas ante patrones anómalos
- [ ] SAST (Bandit/Semgrep) y SCA (pip-audit) en cada PR

### 9.3 Conexión con bancos
- [ ] Due diligence del agregador: certificaciones (ISO 27001 / SOC 2), retención de datos, subprocesadores,
      responsabilidades contractuales ante brechas
- [ ] Credenciales del agregador solo en el servidor, con alcance mínimo y rotación; nunca en el cliente
- [ ] Consentimiento explícito, granular y revocable (Ley Fintec, art. 23); prueba de que el enlace bancario
      de un usuario no se puede asociar a otra cuenta
- [ ] Relay "sealed box" (§5): verificar que el texto en claro no queda en logs, volcados de errores ni
      herramientas de monitoreo/APM (el punto de fuga más común)
- [ ] Minimización: solo los permisos necesarios (movimientos); nunca pedir ni guardar la clave bancaria
- [ ] Integridad de lo sincronizado: deduplicación y conciliación de saldo corrido para detectar datos
      alterados o faltantes
- [ ] Si se consume Finanzas Abiertas directo: certificación de seguridad de interfaces y pruebas funcionales
      por terceros (NCG 514, Anexo 3), FAPI 2.0 / mTLS

### 9.4 Apps cliente
- [ ] Celular (OWASP MASVS): claves en Keychain/Keystore, pantalla oculta en el selector de apps, nada
      sensible en logs ni en respaldos del teléfono, pinning de certificado
- [ ] PWA: CSP estricta y revisión de XSS (en una PWA con E2EE, un XSS equivale a robar las claves), control
      de la cadena de dependencias JavaScript (SRI, versiones fijadas)

### 9.5 Antes de cobrar y de forma continua
- [ ] Pentest externo (API, web, celular) y re-test tras corregir
- [ ] Pagos con página alojada del procesador (Flow/Mercado Pago): los datos de tarjeta nunca pasan por el
      servidor, alcance PCI DSS mínimo
- [ ] Ley 21.719: evaluación de impacto, procedimiento de notificación de brechas, política de privacidad,
      contratos con encargados
- [ ] Plan de respuesta a incidentes (con simulacro) y canal de reporte de vulnerabilidades (`security.txt`)
- [ ] Periódico: pentest anual, revisión trimestral de accesos, rotación de claves, simulacros de restauración

## 10. Cumplimiento legal (a validar con abogado)

- Ley 21.719 (datos personales, vigente desde diciembre de 2026): política de privacidad, bases de
  licitud, derechos de los titulares, notificación de brechas. El E2EE reduce el riesgo, no elimina
  las obligaciones sobre datos de cuenta y pago.
- Ley del Consumidor (SERNAC): términos claros de la suscripción y su cancelación; evitar promesas
  absolutas de seguridad.
- Ley Fintec: aplica si se consume Finanzas Abiertas directamente (ver §5).
- Mantener el aviso "no es asesoría financiera".

## 11. Hoja de ruta sugerida

| Fase | Entrega | Depende de |
|---|---|---|
| 0 ✅ | Bóveda cifrada local, código de recuperación, respaldos cifrados | — |
| 1 | Servicio de identidad: registro, verificación de email, inicio de sesión (§3.1–3.3), 2FA, dispositivos; sincronización de blob cifrado; bloqueo automático por inactividad; instalador firmado | Servidor mínimo (FastAPI) |
| 2 | Suscripción: planes, pagos por webhook, licencia firmada con gracia offline y modo solo lectura (§3.4–3.5); licencia del repositorio; auditoría de seguridad externa | Fase 1 + procesador de pagos |
| 3 | PWA para celular (consulta, registro manual, recurrentes, metas), desbloqueo con biometría | Fase 1; portar lógica de análisis |
| 4 | Conexión con bancos vía agregador con "sealed box" (opcional por usuario) | Fase 3; contrato con agregador |
| 5 | Sincronización por eventos; evaluar inscripción PSBI | Volumen de usuarios |
