El flujo de trabajo será el siguiente:
- (Opcional) dibujo de un boceto 2D o sketch con puntos, barras y restricciones geométricas y dimensionales.
- Definición del modelo con elementos (PuntualMass, Bar, Body), conexiones entre elementos y a ground con rótula o slider.
- Definición de centro de masas, cargas y actuadores.
- Definición de sensores
- Simulación
- Gráficas y analisis de datos

La GUI debe ser muy user-friendly.
Todo debe ser serializable a JSON.
La app en general debe se extensible.

La Interfaz de Ususario tendría los siguientes elementos:

RIBOON:
* EDIT:
	• Do/Undo: muy importante que sea aplicable a toda la app.
    • New Project
	• Load Project
	• Save
	• Export
* SKETCH:
	• Elements:
		• Point
		• Line (segment)
		• Circle
		• Infinite line
		• Square/rectangle
		• Arc
	• Constraints:
    Las restricciones se deben indicar en el sketch con cotas, o símbolos al lado de los elementos.
        • Distance (or line length), point-line distance, diameter
        • Projected distance, along a line or vector
        • Angle
        • Curve-to-curve tangency
        • Parallel
        • Perpendicular
        • Horizontal
        • Vertical
        • Equal length, equal angle, equal radius
        • Length ratio (No prioridad)
        • Line length equals arc length (No prioridad)
        • Point on line, point on circle, point on point.
        • Point at midpoint of line.
        • Points (or line) symmetric about line
        • Dimensions entered as arithmetic expressions (32.6 + 5/25.4) (No prioridad)
            • Image:
                • Ajustar posición según referencia (esquina inferior, superior, derecha o izquierda)
                • Ajustar tamaño en dimensión y porcentaje, con opción de mantener o no la relación de aspecto.
                • Rotar
* MODEL:
	• Elements:
        • Marker:
            • No es un elemento en sí. Vive en el los elementos PunctualMass Bar y Body y sirve para añadir rótulas, masas, cargas, actuadores, etc.
        • PuntualMass: 
            • Masa 1D, representar con circulo de diámetro mayor que las juntas.
            • Tendrá un Marker en el centro.
            • Se podrá pinchar en el marcher y arrastrarlo a la posición que convenga.
            • Tendrá el CM (Centro de masas) en el Marker único.
        • Bar: 
            • Clicar en el canvas dos veces para crearlo.
            • Generará dos Markers unidos por una barra de un ancho, mas un Marker para el centro de masas (en el centro por defecto, aunque se puede desplazar en la línea que une ambos markers.
            • Botón derecho--> añadir Marker --> Clicar en el canvas para añadir Marker y convertirlo en un Body.
            • Si al crear una barra se pincha sobre un marker ya existente, se creará una junta rótula por defecto.
        • Body: 
            • Similar a una barra pero formado por varios markers, al menos 2.
            • En este caso el CM no tiene por que estar en la linea que une ambos elementos.
            • Visualmente tomará forma de polígono incluyendo todos los markers en su interior. El marker destinado al centro de masas no se usará para formar el polígono visual, a no ser que quede fuera del polígono formado por el resto.
        • Junta rótula:
            • Para hacer efectiva al unión se deberán seleccionar Markers de diferentes elementos (Bar, Body, PuntutalMass, etc.)
            • Por defecto el Marker seleccionado en primer lugar se moverá a la posición del Marker en segundo lugar, aunque esto lo marcará más bien el solver si hay restricciones geométricas o dimensionales.
            • La junta rótula permitirá añadir fricción Coulomb y viscosa.
            • Botón derecho sobre una rótula permitirá fijar a Ground.
        • Función Attach:
            • Se abrirá una ventana de diálogo que permitirá seleccionar si se unirán elementos como una rótula o solidarios.
            • Para hacer efectiva al unión se deberán seleccionar Markers de diferentes elementos (Bar, Body, PuntutalMass, etc.)
            • En caso de seleccionar rótula se unirán ambos elementos como una rótula. Por defecto el Marker seleccionado en primer lugar se moverá a la posición del Marker en segundo lugar, aunque esto lo marcará más bien el solver si hay restricciones geométricas o dimensionales.
        • Función Merge:
            • Se seleccionarán 2 elementos del tipo Bar, Body o PuntutalMass y se unirán en un Body reunificando los markers
            • Si hay dos Markers en la misma posición, solo que dejará uno.
            • El centro de masas se recalculará para sumar espacialmente los centro de masas de los elementos unidos.
        • Actuador rotativo:
        • Actuador lineal:
        • Sensores:
            • ...
        

WIDGET DE MODELOS Y CASOS (No prioridad)
Permitirá crear y manejear distintos modelos así como crear diferentes estudios sobre el mismo modelo para realizar análisis de distintas cargas por ejemplo.

ARBOL DEL MODELO:
Incluirá varias pestañas mostrando de manera jerárquica los diferentes elementos que se vayan creando:
* Pestaña “Parámetros”:
Permitirá definir parámetros con sus unidades, que se podrán utilizar para parametrizar tanto el sketch como el modelo.
* Pestaña “Sketch”:
Árbol de elementos y restricciones.

PROPIEDADES / INSPECTOR:
Definirá un menú de propiedades e información asociados al elemento seleccionado y permitirá cambiarlos.

CANVAS:
Lienzo donde se dibuja tanto el Sketch como el modelo. Opciones para mostrar/ocultar el sketch o el modelo. Cuando se esté trabajando con el modelo, el sketch se atenuará. Cuando se est´re trabajando sobre el sketch, el modelo pasará a segundo plano y se atenuará.
Hay que tener en cuenta que en la pantalla de diseño de la cinemática, lo que se está definiendo es el pantallazo en posición t=0 a partir de la cual se va a simular.
Los elementos se podrán fijar (snap) al sketch para t=0, pero posteriormente no se tendrán en cuenta si hay cálculos de trayectorias cinemáticas y el sistema evolucionará dinámicamente sin tener en cuenta esos snap. Solo aplicarán los elementos propios del modelo:

Se debe permitir tanto pinchar un elemento, marker, junta, etc. en el canvas como en el árbol. Esto debe ser equivalente.

SKETCH:
* El sketch es opcional dentro de un proyecto y una capa base que sirve como andamio de construcción al modelo cinemático/dinámico.
* Existirá la opción de utilizarlo si se ha instalado al menos un solver. (por decidir sorver base, por ejemplo sovespace)
* En caso de no detectarse solver se podrán dibujar los elementos y moverlos/posicionarlos por el canvas de manera manual en el menú de edición, pero no se podrán añadir restricciones: el punto se podrá arrastrar o introducir las coordenadas, para la línea se podrán mover o definir la posición de los puntos de inicio y fin, la circunferencia se podrá definir el centro y el radio, del arco se podrán indicar manualmente las coordenadas de los 3 puntos que lo definen, etc.

SIMULACIÓN:
Hará la traducción del modelo generado en la aplicación al solver correspondiente y permitirá simularlo. Se incluirá una linea temporal para moverse por la simulación.

CONSOLA DE SCRIPTING:
Todas las funciones que se puedan realizar sore la GUI debe de ser también posible generarlas en la consola. De hecho la app debe funcionar como una librería y la GUI debe de ser opcional.

LOG:
Cuadro log.