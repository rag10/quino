from qt.widget_Plotter import Ui_widget_Plotter
import os
import sys
import numpy as np
from PyQt5.QtCore import Qt, QRectF, pyqtSignal, QT_VERSION_STR
from PyQt5.QtGui import QImage, QPixmap, QPainterPath, QColor, QBrush
from PyQt5.QtWidgets import QPushButton, QApplication, QWidget, QCheckBox, QDialog, QFileDialog, QSizePolicy, QVBoxLayout, QMessageBox, QGraphicsScene, QGraphicsView, QTreeWidget, QTreeWidgetItem, QDoubleSpinBox
from PyQt5.QtCore import Qt
import copy
import pyqtgraph as pg
from functools import partial
from readDataFiles import read_data_file, AWGdata
import random

#-----------------------------------------------------------------------------------------------------------------------
#  Lista de colores para el plot. En caso de necesitar más se añadirán aleatoriamente

color_set = [(255, 255, 0),
             (255, 0, 0),
             (0, 255, 0),
             (0, 0, 255),
             (255, 0, 255),
             (0, 255, 255),
             (255, 127, 0),
             (0, 255, 127),
             (127, 0, 255),
             (255, 0, 127),
             (127, 255, 0),
             (0, 127, 255)]

#-----------------------------------------------------------------------------------------------------------------------
# Objeto 'MATRIX': en ella se cargarán en una lista diferentes canales en la lista 'channels'.
#                 El primer canal será el tiempo (coordenada x por defecto)

class MATRIX(QTreeWidgetItem):
    def __init__(self, name):
        super(MATRIX, self).__init__()
        self.ID = None
        self.name = name
        self.CHANNELS = []
        self.x = 0
        self.setText(0, self.name)

        for i in range(8):
            self.setBackground(i,QColor(200,200,200))

    def initialize(self):
        self.pushButton_reset_shift = QPushButton('Reset')
        self.pushButton_reset_shift.clicked.connect(self.reset_shifts)
        self.treeWidget().setItemWidget(self, 6, self.pushButton_reset_shift)

        self.pushButton_reset_mult = QPushButton('Reset')
        self.pushButton_reset_mult.clicked.connect(self.reset_mults)
        self.treeWidget().setItemWidget(self, 7, self.pushButton_reset_mult)

    def reset_shifts(self):
        for channel in self.CHANNELS:
            channel.doubleSpinBox_shift.setValue(0.0)

    def reset_mults(self):
        for i, channel in enumerate(self.CHANNELS):
            if i > 0:
                channel.doubleSpinBox_mult.setValue(1.0)

    def __del__(self):
        print('Matrix ', self.name, ' was deleted')



#-----------------------------------------------------------------------------------------------------------------------
# Objeto 'Channel': del tipo QTreeWidgetItem, en ella se almacena cada vector de valores.
#                  Cada canal se almacena en la lista 'CHANNELS' de un objeto 'Matrix'

class CHANNEL(QTreeWidgetItem):
    def __init__(self, parent, name, data, isTime=False, color = (255, 255, 255)):
        super(CHANNEL, self).__init__(parent)

        self.matrixID = None
        self.ID = None
        self.name = name # Nombre
        self.data = data  # Ventor de valores
        self.isTime = isTime  # Bool para definit si es un canal de tiempo
        self.color = color  # Color

        self.curve = None
        self.shift = 0.0
        self.mult = 1.0

    @property
    def x(self):
        return self.checkBox_x.isChecked()

    @property
    def y(self):
        return self.checkBox_y.isChecked()

    def initialize(self):
        # Column 0 - color:
        #self.setBackground(0, QColor(self.color[0], self.color[1], self.color[2]))
        # Column 1 - x (checkBox):
        self.checkBox_x = QCheckBox()
        if self.isTime:
            self.checkBox_x.setChecked(True)
        self.treeWidget().setItemWidget(self, 1, self.checkBox_x)
        self.setBackground(1, QColor(self.color[0], self.color[1], self.color[2]))
        # Column 2 - y (checkBox):
        self.checkBox_y = QCheckBox()
        self.checkBox_y.setChecked(True)
        self.treeWidget().setItemWidget(self, 2, self.checkBox_y)
        self.setBackground(2, QColor(self.color[0], self.color[1], self.color[2]))
        # Column 3 - Name (str):
        self.setText(3, self.name)
        # Column 4 - Mmin (float):
        self.setText(4, str(min(self.data)))
        # Column 5 - Max (float):
        self.setText(5, str(max(self.data)))
        # Column 6 - Shift:
        self.doubleSpinBox_shift = QDoubleSpinBox()
        self.treeWidget().setItemWidget(self, 6, self.doubleSpinBox_shift)
        # Column 7 - Multiplier:
        if not self.isTime:
            self.doubleSpinBox_mult = QDoubleSpinBox()
            self.treeWidget().setItemWidget(self, 7, self.doubleSpinBox_mult)
            self.doubleSpinBox_mult.setDecimals(6)
            self.doubleSpinBox_mult.setRange(-1000000, 1000000)
            self.doubleSpinBox_mult.setSingleStep(0.1)
            self.doubleSpinBox_mult.setValue(1)

        if self.isTime:
            self.checkBox_y.setChecked(False)
            self.checkBox_y.setEnabled(False)
            self.setForeground(2, QBrush(QColor("grey")))
            self.setForeground(3, QBrush(QColor("grey")))
            self.setForeground(4, QBrush(QColor("grey")))
            self.setForeground(5, QBrush(QColor("grey")))
            self.setForeground(6, QBrush(QColor("grey")))

    def set_color(self,color=None):
        if color is not None:
            self.color = color
        self.curve.setPen(pg.mkPen(color = self.color))

    def data2plot(self):
        return self.data*self.mult + self.shift

    def update_plot(self, x):
        if self.curve is not None:
            self.shift = self.doubleSpinBox_shift.value()
            if not self.isTime:
                self.mult = self.doubleSpinBox_mult.value()
            self.doubleSpinBox_shift.setDecimals(6)
            self.doubleSpinBox_shift.setRange(-abs(min(self.data)) - abs(100*(max(self.data)-min(self.data))), abs(max(self.data)) + abs(100*(max(self.data)-min(self.data))))
            self.doubleSpinBox_shift.setSingleStep((max(self.data) - min(self.data))/1000)
            data = np.column_stack((x, self.data2plot()))
            self.curve.setData(data)

    def __del__(self):
        print('Channel ', self.name, ' was deleted')

#-----------------------------------------------------------------------------------------------------------------------
# Objeto widget qt 'PLOTTER'

class widget_Plotter(QWidget):
    def __init__(self, parent = None):
        super(widget_Plotter, self).__init__(parent)
        self.ui = Ui_widget_Plotter()
        self.ui.setupUi(self)

        self.MATRICES = []

        self.headers = ('','x', 'y', 'Name', 'Min', 'Max','+','x','')
        self.ui.treeWidget.setColumnCount(len(self.headers))
        self.ui.treeWidget.setHeaderLabels(self.headers)
        self.ui.treeWidget.selectionMode = QTreeWidget.ExtendedSelection

        for column in range(1,self.ui.treeWidget.columnCount()):
            self.ui.treeWidget.resizeColumnToContents(column)

        self.ui.treeWidget.expandAll()

        # CONNECT SIGNALS
        self.ui.treeWidget.itemSelectionChanged.connect(self.selection_changed)
        self.ui.toolButton_delete.clicked.connect(self.delete_selected)
        self.ui.toolButton_import_matrix.clicked.connect(self.import_matrix)
        self.ui.toolButton_export.clicked.connect(self.export_matrix)

        self.pg_graphicsWindow = pg.GraphicsLayoutWidget()
        self.ui.verticalLayout_plot.addWidget(self.pg_graphicsWindow)
        self.pg_plot = self.pg_graphicsWindow.addPlot()
        self.pg_plot.showGrid(True,True,0.5)


        self.color_counter = 0

        self.ui.toolButton_delete.setEnabled(False)
        self.ui.toolButton_export.setEnabled(False)
        self.ui.splitter_main.setSizes([200,800])

    def selection_changed(self):
        items = self.ui.treeWidget.selectedItems()
        if len(items) == 0:
            self.ui.toolButton_delete.setEnabled(False)
        else:
            self.ui.toolButton_delete.setEnabled(True)

        self.ui.toolButton_export.setEnabled(False)
        if len(items) == 1:
            for item in items:
                if isinstance(item, MATRIX):
                    self.ui.toolButton_export.setEnabled(True)

    def print_matrices(self):
        pass
        # for matrix in self.MATRICES:
        #     print('--> ', matrix.name, matrix.ID)
        #     for channel in matrix.CHANNELS:
        #         print('-----> ', channel.name, channel.matrixID, channel.ID)
        # print('----------------------------------------------------------')

    def update_count(self):
        self.mCount = -1
        self.chCount = -1
        for matrix in self.MATRICES:
            self.mCount = self.mCount + 1
            matrix.ID = self.mCount
            self.chCount = -1
            for i_ch, channel in enumerate(matrix.CHANNELS):
                self.chCount = self.chCount + 1
                channel.matrixID = self.mCount
                channel.ID = self.chCount

    def delete_selected(self):
        items = self.ui.treeWidget.selectedItems()
        for item in items:
            try:
                self.delete(item)
            except: pass

    def delete(self,item):
        if isinstance(item, MATRIX):
            self.ui.treeWidget.invisibleRootItem().removeChild(item)
            for channel in item.CHANNELS:
                self.pg_plot.removeItem(channel.curve)
            del self.MATRICES[item.ID]
        elif isinstance(item, CHANNEL):
            self.pg_plot.removeItem(item.curve)
            self.pg_plot.show()
            item.parent().removeChild(item)
            del self.MATRICES[item.matrixID].CHANNELS[item.ID]
            self.delete_empty_matrices()
        self.update_count()
        self.update_all_plots()


    def delete_empty_matrices(self):
        for matrix in self.MATRICES:
            if len(matrix.CHANNELS) == 0:
                self.delete(matrix)
                self.update_count()

    def import_matrix(self):
        files, dummy = QFileDialog.getOpenFileNames(parent=self,
                                                  caption='Open file',
                                                  directory=str(os.path.expanduser('~')))
        for file in files:
            file_path, file_name = os.path.split(file)
            try:
                data, headers = read_data_file(file)
                self.load_matrix(data = data, headers= headers, matrix_name=file_name)
            except:
                QMessageBox.warning(self, 'Import', 'Error importing ' + str(file_name))

    def load_matrix(self, data, headers = None, matrix_name='...'):
        N_channels = data.shape[1]
        if headers == None:
            headers = []
            for i in range(0, N_channels):
                headers.append('CH' + str(i + 1))
        if len(headers) == N_channels:
            self.MATRICES.append(MATRIX(matrix_name))
            self.ui.treeWidget.addTopLevelItem(self.MATRICES[-1])
            self.MATRICES[-1].initialize()
            for i in range(0, N_channels):
                if i == 0:
                    self.MATRICES[-1].CHANNELS.append(CHANNEL(parent = self.MATRICES[-1],
                                                              name=headers[i],
                                      data=data[:, i],
                                      isTime=True,
                                      color=[255, 255, 255]))
                else:
                    self.MATRICES[-1].CHANNELS.append(CHANNEL(parent = self.MATRICES[-1],
                                                              name=headers[i],
                                      data=data[:, i],
                                      isTime=False,
                                      color=self.next_color()))

                self.update_count()
                self.MATRICES[-1].CHANNELS[i].initialize()
                self.MATRICES[-1].CHANNELS[i].curve = self.pg_plot.plot()
                self.MATRICES[-1].CHANNELS[i].update_plot(x=self.MATRICES[-1].CHANNELS[0].data)
                self.MATRICES[-1].CHANNELS[i].checkBox_x.clicked.connect(partial(self.x_changed, self.MATRICES[-1].CHANNELS[i]))
                self.MATRICES[-1].CHANNELS[i].checkBox_y.clicked.connect(partial(self.update_channel_plot, self.MATRICES[-1].CHANNELS[i]))
                if i == 0:
                    self.MATRICES[-1].CHANNELS[i].doubleSpinBox_shift.valueChanged.connect(partial(self.update_matrix_plots,self.MATRICES[-1]))
                else:
                    self.MATRICES[-1].CHANNELS[i].doubleSpinBox_shift.valueChanged.connect(partial(self.update_channel_plot, self.MATRICES[-1].CHANNELS[i]))
                    self.MATRICES[-1].CHANNELS[i].doubleSpinBox_mult.valueChanged.connect(partial(self.update_channel_plot, self.MATRICES[-1].CHANNELS[i]))

            print('Data loaded: ' + str(self.mCount))
            self.ui.treeWidget.expandAll()
            self.update_all_plots()
            if len(self.MATRICES) == 1:
                for column in range(1, self.ui.treeWidget.columnCount()):
                    self.ui.treeWidget.resizeColumnToContents(column)

    def load_channels_to_matrix(self,matrixID,data,headers):
        pass

    def export_matrix(self):
        items = self.ui.treeWidget.selectedItems()
        headers=''
        if len(items) == 1:
            for matrix in items:
                if isinstance(matrix, MATRIX):
                    data = np.zeros((matrix.CHANNELS[0].data.size,len(matrix.CHANNELS)))
                    file, dummy = QFileDialog.getSaveFileName(parent=self,
                                                              caption='Export to file',
                                                              directory= ('Ensayos_piston/'+matrix.name), # str(os.path.expanduser('~')),
                                                              filter='Text Files (*.txt);;All Files (*)')
                    for i, channel in enumerate(matrix.CHANNELS):
                        data[:,i] = channel.data2plot()
                        headers = headers + channel.name + '\t'
                    try:
                        np.savetxt(fname=file, X=data, delimiter='\t', header=headers, comments='')
                    except:
                        QMessageBox.warning(self, 'Export', 'Error exporting data')


    def x_changed(self, changed_channel):
        matrix = self.MATRICES[changed_channel.matrixID]
        if changed_channel.checkBox_x.isChecked():
            ix = changed_channel.ID
            matrix.x = ix
            for channel in matrix.CHANNELS:
                if channel is not changed_channel:
                    channel.checkBox_x.setChecked(False)
        else:
            matrix.CHANNELS[0].checkBox_x.setChecked(True)
            matrix.x = 0
        self.update_matrix_plots(matrix)

    def update_all_plots(self):
        self.update_count()
        for matrix in self.MATRICES:
            for channel in matrix.CHANNELS:
                channel.update_plot(x=matrix.CHANNELS[matrix.x].data + matrix.CHANNELS[matrix.x].shift)
                channel.set_color()
                if channel.checkBox_y.isChecked():
                    channel.curve.show()
                else:
                    channel.curve.hide()
        if len(self.MATRICES) > 0:
            self.ui.toolButton_delete.setEnabled(True)
        else:
            self.ui.toolButton_delete.setEnabled(False)

    def update_matrix_plots(self, matrix):
        for channel in matrix.CHANNELS:
            channel.update_plot(x=matrix.CHANNELS[matrix.x].data + matrix.CHANNELS[matrix.x].shift)
            channel.set_color()
            if channel.checkBox_y.isChecked():
                channel.curve.show()
            else:
                channel.curve.hide()

    def update_channel_plot(self, channel):
        matrix = self.MATRICES[channel.matrixID]
        channel.update_plot(x=matrix.CHANNELS[matrix.x].data + matrix.CHANNELS[matrix.x].shift)
        channel.set_color()
        if channel.checkBox_y.isChecked():
            channel.curve.show()
        else:
            channel.curve.hide()

    def next_color(self):
        self.color_counter = self.color_counter + 1
        if self.color_counter <= len(color_set):
            return color_set[self.color_counter-1]
        else:
            return(int(random.random() * 256) % 256, int(random.random() * 256) % 256,int(random.random() * 256) % 256)

    def N_matrices(self):
        return len(self.MATRICES)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    PLOTTER = widget_Plotter()
    #data, headers = read_data_file('060618_pos0.txt')
    #PLOTTER.load_matrix(data=data, headers=headers, matrix_name='pos0.txt')
    PLOTTER.show()
    app.exec_()
