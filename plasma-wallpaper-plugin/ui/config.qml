import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Kirigami.FormLayout {
    property alias cfg_Image: imageField.text
    property alias cfg_FontSize: fontSpin.value
    property alias cfg_Margin: marginSpin.value
    property string cfg_Corner: "topright"

    QQC2.TextField {
        id: imageField
        Kirigami.FormData.label: "Файл обоев:"
        Layout.fillWidth: true
    }
    QQC2.SpinBox {
        id: fontSpin
        Kirigami.FormData.label: "Размер шрифта:"
        from: 8; to: 40
    }
    QQC2.SpinBox {
        id: marginSpin
        Kirigami.FormData.label: "Отступ от края:"
        from: 0; to: 400
    }
    QQC2.ComboBox {
        Kirigami.FormData.label: "Угол:"
        model: ["topleft", "topright", "bottomleft", "bottomright"]
        currentIndex: model.indexOf(cfg_Corner)
        onActivated: cfg_Corner = model[currentIndex]
    }
}
