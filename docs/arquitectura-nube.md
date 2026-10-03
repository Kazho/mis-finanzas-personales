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
- Finanzas Abiertas: consumir las APIs de los bancos directamente exige ser PSBI. Los requisitos
  verificados contra la norma están en §5.1. Recomendación: partir con un agregador ya habilitado y evaluar
  la inscripción propia solo si el volumen lo justifica.

### 5.1 Lo que exige la CMF (Sistema de Finanzas Abiertas) — revisión de octubre de 2026

**Qué se leyó y qué no.** El texto original de la NCG 514 (julio de 2024) se leyó completo, directo del PDF
de la CMF. La modificación de junio de 2026 (NCG 569, que incorpora el Anexo Técnico N°3) se conoce solo por
el comunicado de la CMF y resúmenes de estudios jurídicos: **hay que leer su texto y el Anexo 3 antes de
construir**. Lo marcado "(por verificar)" viene de fuentes secundarias.

**Calendario.** La norma entra en vigencia en **julio de 2027** (antes julio de 2026). Eso no significa que
los movimientos estén disponibles ese día: los bancos tienen un plazo posterior para habilitar cada API.
En el texto original, para personas naturales: 6 meses para términos y canales, **15 meses** para
enrolamiento, posiciones, historial de transacciones y productos vigentes (18 meses las líneas de crédito).
La modificación redefine esos plazos "entre 5 y 18 meses" (por verificar el detalle), y una fuente indica que
la operación plena podría extenderse hasta 2030 mientras falte el Anexo 4 de costos. **Planificar con que las
APIs de movimientos estarán disponibles entre fines de 2027 y 2029, no en julio de 2027.** Hay además un
periodo piloto de 60 días y un *sandbox* de la CMF para probar antes.

**Quién puede pedir los datos.** Solo participantes inscritos en el Registro de PSBI (Prestadores de Servicios
Basados en Información) o habilitados en la nómina especial si ya son proveedores financieros inscritos.
La inscripción es voluntaria pero **solo para personas jurídicas chilenas** (o extranjeras con agencia en Chile),
presentada por su representante legal, con estatutos, socios principales (≥10%) y malla societaria. Una persona
natural no puede inscribirse. Una app instalada por el usuario (escritorio o celular) **no consulta al banco
directamente**: lo hace el conector, que es el PSBI, con el consentimiento del cliente. El usuario "dueño de sus
datos" los obtiene por el conector, no por una API personal.

**Autenticación.** El banco debe autenticar al PSBI con un certificado digital emitido por una autoridad de
validación extendida y contrastar sus permisos con el Directorio de Participantes de la CMF; el cliente se
autentica en su banco con autenticación reforzada (dos factores independientes). Estándares: OAuth 2.0 y OpenID
Connect, API REST/JSON y OpenAPI 3.1; los perfiles FAPI 2.0 y mTLS se mencionan en fuentes secundarias (por
verificar en el Anexo 3).

**Consentimiento** (sección III.D de la norma). Debe ser expreso, específico (qué datos, a qué institución, por
cuánto tiempo o con qué frecuencia y para qué finalidad), guardado en un soporte duradero, y sin interfaces
que lo induzcan (nada premarcado, ni condicionar el servicio a ceder datos que no necesita). Se piden solo los
datos estrictamente necesarios y se usan solo para la finalidad consentida. Obliga a ofrecer un **panel de
control gratuito, remoto y autenticado** donde el cliente vea y revoque cada consentimiento (institución,
finalidad, datos, fecha y hora, plazo, estado), con registro íntegro de accesos por **5 años**, historial de
consentimientos de 5 años, **revocación en tiempo real** entre participantes y un aviso si el cliente no
entra al panel en un año.

**Qué datos y cada cuánto.** Historial de uso y transacciones: actualización diaria, disponible hasta 5
minutos después, historia de 12 meses en el texto original (la modificación la llevaría a 24 meses, por
verificar). Posiciones históricas: saldos mensuales.

**Costos.** Los bancos no pueden cobrar a un PSBI, salvo reembolso de costos incrementales al superar umbrales
de llamadas: para historial de transacciones, posiciones y productos, **150 llamadas mensuales por cliente y por
PSBI**. El Anexo 4 (costos) estaba pendiente. Conviene diseñar la sincronización para consumir pocas llamadas
(una consulta diaria por cliente ya es ~30 al mes).

**Qué obliga a guardar 5 años (y qué no).** La norma menciona los 5 años en tres lugares:
1. Registro de los eventos de las APIs, incluida "la información que se transmite" (sección III.B.3.c). Está en el
   apartado de seguridad y contingencia **de las APIs**, dirigido a las "entidades supervisadas" que las operan, es decir
   los bancos que las exponen; un PSBI las consume y no las expone. Por verificar en la NCG 569 y el Anexo 3.
2. Registro íntegro de los **accesos e interacciones de los clientes con el panel de control** (III.D.2.e).
3. Visualización de los **consentimientos** otorgados, revocados o caducados en los últimos 5 años (III.D.2.f).

Los puntos 2 y 3 sí alcanzan al PSBI, pero son datos del consentimiento, no de las finanzas del cliente. **Ninguno
obliga a un PSBI a conservar los movimientos.** Esos datos los tiene el banco, y la app solo los muestra en una
herramienta consolidada, de modo que pueden vivir únicamente en el dispositivo del usuario, que es lo que promete este
plan. Pendiente para el abogado: confirmar que el punto 1 no alcanza al PSBI en la norma vigente, y fijar el plazo de
conservación de cada dato que sí se guarde (consentimientos, bitácora del panel, registros de seguridad sin contenido
financiero) en el registro de actividades de tratamiento, bajo el principio de no guardar más de lo necesario (Ley 21.719).

### 5.2 Modelo elegido: empresa propia como PSBI, solo lectura

Decisión del producto (octubre de 2026): se constituye una **empresa** que será el PSBI, y los usuarios solo le
otorgan permiso de **consulta** de sus datos. No se inicia ningún pago.

**Por qué "solo consulta" simplifica.** Los proveedores de iniciación de pagos (PSIP) deben, además, acreditar
garantías (póliza o boleta bancaria renovadas cada trimestre), cumplir requisitos del Banco Central y un plan para
que no queden transacciones pendientes. Nada de eso aplica a un PSBI. Conviene no ofrecer nunca pagos desde la
app mientras se quiera mantener este perfil de bajo riesgo regulatorio.

**Qué debe presentar la empresa para inscribirse** (NCG 514, sección I.C; texto original, por verificar contra
la NCG 569 y el Anexo 3). Se presenta por el canal electrónico de la CMF, firmado por el representante legal, que
responde personalmente por la veracidad:

| Letra | Antecedente |
|---|---|
| a | Estatutos y certificados de vigencia (en sociedades de la Ley 20.659, el certificado de incorporación y estatuto actualizado) |
| b | Poder del representante que presenta la solicitud |
| c | Plan de negocios: servicios que dará como PSBI, tipo de clientes y qué conjuntos de datos del sistema usará |
| d | Organigrama: cargos clave, comités y quién responde por cumplir los requisitos de gestión, operativos y de seguridad |
| e | Relación con clientes: servicios y condiciones, cómo se garantiza el funcionamiento del consentimiento y la autenticación, cómo ejercen sus derechos |
| f | Consentimiento: los textos exactos con que se pide y el flujo de obtención, registro, resguardo y gestión (art. 23 Ley Fintec) |
| g | Tratamiento de datos personales: cómo se registra, controla y restringe el acceso, medidas técnicas y organizativas, y el **registro de actividades de tratamiento** (finalidad, plazo de conservación, base de licitud, categorías de datos y de destinatarios) |
| h | Declaración jurada de no tener la inhabilidad del art. 19 de la Ley Fintec |
| i | Políticas de gestión de riesgos y control interno (sección III de la norma) |
| j | **Certificado** de correcta implementación de los perfiles de seguridad de interfaces, emitido por un tercero (condiciones en el Anexo 3) |
| k | Certificado de no estar en quiebra ni en procedimiento concursal (máximo 30 días de antigüedad) |
| l | **Reporte de pruebas funcionales** de consumo de las APIs en el área de pruebas, hecho por un tercero (Anexo 3) |

Además se pagan los derechos del art. 33 del D.L. 3.538 (monto por consultar), y cualquier cambio en lo declarado
se informa a la CMF dentro de 5 días hábiles.

**Qué debe cumplir y operar de forma continua** (sección III, aplica a todos los participantes):
- El directorio u órgano equivalente aprueba cada año las políticas de gestión de riesgos y de seguridad.
- Plan de gestión de riesgos, riesgo operacional y control de proveedores externos (el hosting y los subcontratos
  también quedan bajo responsabilidad de la empresa).
- Seguridad de la información y ciberseguridad: procedimientos de respuesta y recuperación ante incidentes
  actualizados al menos una vez al año, gestión de cambios con pruebas de seguridad antes de pasar a producción,
  gestión de obsolescencia y de parches, y **pruebas de vulnerabilidades al menos una vez al año**, con
  resultados reportados al directorio.
- **Reportar a la CMF** los incidentes operacionales y de ciberseguridad (fugas de información, indisponibilidad,
  malware, fraude) y avisar a los clientes afectados.
- Panel de control del consentimiento accesible desde la web (§5.1), con registros de 5 años.
- Acceso a las APIs de los bancos con certificado digital propio, sin necesidad de acuerdos comerciales con cada
  banco (la norma prohíbe a los bancos discriminar o exigir pactos adicionales).

**Qué cambia en la arquitectura frente al plan con agregador (§5):**
- La empresa es directamente responsable ante la CMF, no un tercero. El agregador pasaría a ser, como mucho, un
  puente temporal mientras los bancos no tengan APIs (no antes de fines de 2027, §5.1).
- El panel de consentimiento debe poder usarse también desde la web, no solo desde la app, y el consentimiento se
  guarda **en la empresa** además de en el dispositivo. El cifrado de extremo a extremo protege los movimientos; los
  consentimientos y la bitácora del panel son otra cosa y la norma obliga a conservarlos 5 años. Los movimientos, en
  cambio, no tienen esa obligación para un PSBI (por verificar en la NCG 569), así que pueden quedar solo en el
  dispositivo del usuario.
- El servicio debe separar con claridad el **panel de consentimiento** (obligación regulatoria, gratuito) de la
  **suscripción** (producto): revocar o no pagar no puede bloquear el derecho a ver y revocar consentimientos.

**Orden sugerido (hay margen: los bancos no tendrán las APIs de movimientos antes de fines de 2027):**
1. Constituir la sociedad (con objeto social que incluya servicios habilitados por información financiera),
   designar representante legal y definir el órgano que aprobará las políticas.
2. Contratar asesoría legal en Ley Fintec, protección de datos (Ley 21.719) y consumo; resolver la pregunta
   abierta de §5.1.
3. Leer el texto vigente (NCG 569 y Anexos 3 y 4) y probar en el *sandbox* y el portal del desarrollador de la CMF.
4. Construir el conector y el panel de consentimiento (fases 1 a 4 de la hoja de ruta) con el programa de
   seguridad de §9 y el contrato de ingesta de §12.
5. Contratar a los terceros que certifican las interfaces y hacen las pruebas funcionales (letras j y l).
6. Redactar los documentos de las letras c a i, inscribirse y completar el periodo piloto.

Esto no es asesoría legal: está leído de la norma original y hay que validarlo con un abogado y con la
modificación vigente.

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
- [x] Carga de archivos endurecida (octubre de 2026): tamaño máximo de 25 MB, tipo verificado por la firma real del
      archivo y no por la extensión, nombre saneado, lectura en un **proceso aparte con tiempo límite de 30 s**, y
      datos validados antes de guardar (montos finitos y acotados, fechas razonables, textos sin caracteres de
      control). Motivo medido: un PDF válido de 7 KB que se expande a 2 MB tarda ~30 s y usa ~490 MB al leerse, y el
      costo crece de forma lineal; ahora se rechaza al instante o se corta a los 30 s sin congelar la app
      (`src/seguridad_archivos.py`, `src/lectura_aislada.py`)
- [x] Pruebas de seguridad automáticas de esa carga: archivos disfrazados, bombas de descompresión (también las que
      evaden el filtro previo), Excel y PDF dañados, tiempo límite, datos absurdos (`tests/test_seguridad_archivos.py`);
      fuzzing por mutación de 480 archivos corruptos sin cuelgues ni consumo anormal de memoria
- [x] Análisis estático (bandit) y auditoría de dependencias directas y transitivas (pip-audit) sin hallazgos de
      severidad media o alta ni vulnerabilidades conocidas; se ejecutan en `.github/workflows/pruebas-y-seguridad.yml`
      (el workflow se escribió pero aún no se ha visto correr en GitHub)
- [ ] Límite de **memoria** del proceso lector (hoy solo hay tiempo límite; en 30 s una bomba llega a ~0,5 GB)
- [ ] `xlrd` (lee los `.xls`) no tiene mantenimiento activo y falló de formas internas ante archivos corruptos (hoy se
      convierte en un error claro y corre aislado); evaluar reemplazarlo o seguir fuzzeándolo
- [ ] Probar el `.exe` empaquetado con `--lector-aislado` (el proceso lector se lanza con el propio ejecutable; no se
      ha construido el instalador con este cambio) y medir el costo de arranque de cada lectura
- [ ] Fuzzing periódico (hoy se hizo una vez, a mano) y revisión de la ruta de la actualización automática
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
| 0.5 ✅ | Contrato de ingesta (§12): toda fuente entrega un `LoteImportacion`, un solo camino de guardado, UUID global, fuente e id externo | Fase 0 |
| 1 | Servicio de identidad: registro, verificación de email, inicio de sesión (§3.1–3.3), 2FA, dispositivos; sincronización de blob cifrado; bloqueo automático por inactividad; instalador firmado | Servidor mínimo (FastAPI) |
| 2 | Suscripción: planes, pagos por webhook, licencia firmada con gracia offline y modo solo lectura (§3.4–3.5); licencia del repositorio; auditoría de seguridad externa | Fase 1 + procesador de pagos |
| 3 | PWA para celular (consulta, registro manual, recurrentes, metas), desbloqueo con biometría | Fase 1; portar lógica de análisis |
| 4 | Conexión con bancos vía agregador con "sealed box" (opcional por usuario); el conector entrega lotes por el contrato de §12 | Fase 3; contrato con agregador; APIs de los bancos disponibles (§5.1) |
| 5 | Sincronización por eventos; evaluar inscripción PSBI | Volumen de usuarios |

## 12. Fuentes de datos y contrato de ingesta

El producto es **local primero**: los datos del usuario viven cifrados en su dispositivo (escritorio o celular) y
un servicio por suscripción (el conector) trae los movimientos desde los bancos. Para que pasar de archivos a
APIs sea cambiar una fuente y no reescribir la app, toda entrada de datos pasa por un único contrato:

```
 Archivo PDF / Excel ──▶ parser ──▶ adaptador de archivo ─┐
                                                          ├─▶ LoteImportacion ─▶ validar() ─▶ guardar_lote() ─▶ base local cifrada
 Conector (API de bancos) ──────▶ adaptador de API ───────┘      (contrato)       (rechaza el        (una transacción,
                                                                                    lote entero)       idempotente)
```

| Pieza | Archivo | Qué garantiza |
|---|---|---|
| Contrato | `src/fuentes/contrato.py` | Un solo formato de cuenta, movimiento y lote; `validar()` rechaza datos inconsistentes (montos negativos, cargo y abono a la vez, moneda o tipo desconocidos, `id_externo` repetido, sin forma de evitar duplicados) |
| Adaptador de archivos | `src/fuentes/archivo.py` | Traduce lo que devuelven los parsers actuales al contrato; es el único lugar que lo sabe |
| Guardado | `src/ingesta.py` | Todo el lote en una transacción; carga idempotente; reemplaza lo provisional; nunca pisa la categoría que eligió el usuario |
| Interfaz del conector | `src/fuentes/conector.py` | Consentimientos (con los campos que exige la norma), `sincronizar()` que devuelve lotes, y un conector "no configurado" que falla con un mensaje claro |
| Base de datos | `src/db.py` | `fuente`, `id_externo` y `uid` (UUID global) por movimiento y cuenta; índices únicos; el UUID lo asigna la base si falta |

Decisiones que quedan escritas en el código:

- **Idempotencia con id del banco.** Si el movimiento trae `id_externo`, se identifica por (cuenta, id): al
  volver a recibirlo se **actualiza** lo que el banco pudo cambiar (un pendiente que pasa a contabilizado, un monto
  corregido) en vez de duplicarlo. Sin id (archivos) se usa la huella de fecha, glosa y montos.
- **Estado del movimiento.** `facturado` o `por_facturar` equivale a contabilizado o pendiente de una API.
  Los pendientes son provisionales y los reemplaza la siguiente carga.
- **UUID global.** Es lo que permite sincronizar PC y celular por eventos (§4, fase 2) sin que choquen los ids
  autoincrementales de cada dispositivo.
- **Sin secretos en el contrato.** El origen de un lote es una etiqueta; los tokens del conector van solo en la
  bóveda cifrada.

**Pendiente, en orden de importancia antes de automatizar:**

1. **Montos como enteros.** Hoy son `float`. Para dinero conviene guardar la unidad mínima (pesos, centavos de
   dólar) como entero, para que sumas y conciliaciones no arrastren errores de redondeo. Hay que migrarlo antes de
   recibir miles de movimientos automáticos.
2. **Conciliar archivo con API al migrar.** Quien ya cargó PDF tendrá los mismos movimientos llegando por API
   con otra glosa. Hace falta una regla de equivalencia (misma cuenta, fecha, monto y estado), precedencia de la
   API sobre el archivo y una lista de posibles duplicados para revisar, no un borrado automático.
3. **Serialización del contrato.** Definir su esquema JSON (OpenAPI) para el servicio y para un cliente móvil que
   no sea Python.
4. **Identificadores de cuenta del banco** y su relación con el consentimiento que los habilitó.
5. **Almacén de credenciales** del conector dentro de la bóveda: solo lectura, revocable, nunca en logs.
