
* Gravity por defecto OFF.
* Cuando se cambia los parámetros de simulación (tiempo de simulación, numero de frames o delta t), debería anularse la simulación anterior al igual que cuando se cambia algo del modelo.
* El centro de masas de una Punctual Mass no se debe poder desplazar del único marker que la forma. 
* El centro de masas en las barras, debe contenerse en el segmento que une los dos puntos. En vez de definirlo por coordenadas, vamos a definirlo como un porcentaje de la longitud de la barra o como una longitud partiendo del primer marker y como máximo la longitud de la barra (ambas opciones deben poderse editar, cambiando la otra en consecuencia). Si la posición de uno de los markers se modifica, el CoM cambiará en consecuencia manteniendo la distancia relativa y proporcional a los markers.

* Implementar la posibilidad de añadir fricciones a las rótulas. Por defecto se incluirán rótulas y sliders sin fricción y en el inspector se podrá editar. Se debe considerar la posibilidad de incluir fricción de coulomb y/o viscosa.
* Para los selectores de frames: los botones de incremento o reducción deben cambiar en un orden de magnitud inferior al valor de forma que si el valor es 1000, los botones deben cambiar en +/-100. Si el valor es 54608, os botones deben cambiar en +/- 5460
* Para el selector Delta t y speed: deben cambiar de la siguiente forma: si el valor es 0.001, los botones deben cambiar +/-0.0005. Si el valor es 0.003, los botones deben cambiar +/-0.0005. Si el valor es es 0.07, los botones deben cambiar +/-0.005. Si el valor es 2.5, los botones deben cambiar +/-0.5.
* Las cargas deberán poder definirse como función de variables como el tiempo o señales medidas por los sensores. Por ejemplo, en función de una distancia medida entre 2 markers (similar a un muelle), o en función de un ángulo.
* Estudiar si podemos incluir un sistema de coordenada local para los elementos. 
	• Particularidades de cada elemento: 
		• Punctual Mass no tendrá origen de coordenadas.
		• Bar tendrá origen de coordenadas con x alineado siempre con la dirección del segmento. Los markers que definen la barra y el CoM siempre estarán en el eje local x.
		• Body tendrá el sistema un coordenadas que se definirá con respecto al sistema absoluto de coordenadas por desplazamiento y rotación.
	• El origen de coordenadas local no tiene por qué estar en un marker, aunque por defecto se creará en el primer marker que se cree.
	• En el inspector tendríamos un seleccionador para poder editar la posición de los markers con respecto al sistema de coordenadas global o local.
	• El sistema de coordenadas local se debe poder mostrar u ocultar en el canvas. En el model tree deberá aparecer como hijo del elemento y se podrá editar desde el inspector. 
* Correcciones en sketch a nivel GUI: 
	• Añadir por defecto un punto O en el origen y fijo .
	• Cambiar el icono de rectángulo para que sea representativo (ahora es igual que el de línea).
	• El círculo debería poder cambiar el diámetro al arrastrarlo sin cambiar el centro, teniendo en cuenta por supuesto las restricciones que le apliquen.
	• Arco por tres puntos contenidos en el arco lo vamos a eliminar. Solo vamos a dejar la opción de definirlo con el primer marker indicando el centro y los otros dos el inicio y el final del arco. Revísalo bien para que los markers 2 y 3 coincidan con el principio y el final del arco.
	• Restricción de distancia: 
		• Al definirla la distancia entre dos markers, la cota aparece a una distancia fija y siempre la misma. Vamos a mejorar esto poniendo la cota a la distancia que el usiario clique la tercera vez con respecto a los dos primeros markers seleccionados. Para modificar esa distancia desde los markers donde se aplica la restricción hasta donde se muestra la cota, se deberá poder hacer desde el inspector.
		• La restricción de distancia también se podrá definir sobre una linea (no solo sobre 2 markers).
		• Al definir la restricción de distancia en una circunferencia para definir un radio, no se muestra la cota en el canvas, incluye flecha y el valor para mostrarla. Aunque en la GUI se utilice un solo botón para restricciones de distancia entre 2 markers o para definir un radio, a la hora de crearlo deberán ser tipos distintos "distance" / "radius". 
		• Vamos a añadir dos botones y funciones adicionales para añadir restricciones de distancia vertical y horizontal para aplicar la restricción de distancia en la proyección sobre el eje x o y. En este caso solo se podrán seleccionar markers o líneas, no circunferencias.
		• Se debe poder seleccionar las cotas de distancias y radio directamente sobre el valor o la cota en el canvas para poder modificarla en el inspector. Con doble clic se abrirá una pop-up para modificarlo.
	• Al poner una restricción de ángulo, da un error de "Expected angle but got unitless", pero el campo es un spin box que no deja introducir unidades. Arréglalo.
	• Las restricciones de paralelismo, perpendicularidad y equal se deben poder seleccionar desde su símbolo en el canvas. Para una restricción debe aparecer el símbolo en las dos líneas que quedan relacionadas. Eliminar la linea discontinua que indica la restricción para estos casos.
	• En el caso de tangencia, se debe crear un punto adicional en el punto de tangencia entre la línea y la circunferencia. También se debe permitir la tangencia entre dos circunferencias y con arcos.
	• Los elementos que sean construction=True, solo se mostrarán en modo Sketch. En modo Model o Sim, no se mostrarán aunque el sketch esté visible.
	• La restricción de colinearidad debe ser entre dos segmentos.
	• La restricción de coincidencia debe permitir unir 2 markers, pero también hacer pertenecer un punto a una recta o un círculo en función de los 2 elementos que se seleccione. De esta forma podemos incluir "OnCircle" como una restricción de coincidencia. coincidencia.
	• Revisa la restricción de concentricidad entre un arco y una circunferencia.
	• La restricción de simetría debe tener como entrada dos markers y una linea o linea infinita que indique el plano de simetría.
	• El Botón Solve no tiene efecto.


-------------------------------
Vamos a organizar el toolbar de la siguiente forma. Te indico por bloques y posiciones:

Sketch Draw:
point | line | rectangle 
Circle | axis | arc

Sketch Constraints:
Bloques Point y Curve, los vamos a unificar y llamar Constraints, con los botones en dos lineas dividiendo a la mitad el número entre ambas filas.

Elements:
Point | Bar | Body
Marker | Slider

Joints:
Revolute | Rigid
Ground | To slide

Drives:
RotDrv
LinDrv

Sensors:
Point | Dist
Ang H | Ang V | AngRel

Loads:
Load | Torque (por crear)
Gravity

Springs:
RotSpring
LinSpring

Actuators:
RotAct
LinAct