import QtQuick
import QtQuick.Window
import org.kde.plasma.plasmoid

WallpaperItem {
    id: root

    readonly property string cfgImage:
        (root.configuration && root.configuration.Image)
        ? root.configuration.Image
        : "/usr/share/wallpapers/Foreland/contents/images_dark/5120x2880.png"
    readonly property string cfgData:
        (root.configuration && root.configuration.DataPath)
        ? root.configuration.DataPath
        : "/run/user/1000/conky-dash/dash.png"
    readonly property int cfgMargin:
        (root.configuration && root.configuration.Margin) ? root.configuration.Margin : 40
    readonly property string cfgCorner:
        (root.configuration && root.configuration.Corner) ? root.configuration.Corner : "topright"

    // Экран масштабирован (devicePixelRatio), координаты QML — логические.
    // Делим натуральный размер на DPR: один пиксель картинки ложится ровно
    // на один физический пиксель экрана, текст остаётся чётким.
    readonly property real dpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1

    // ---- сами обои ----
    Image {
        anchors.fill: parent
        source: root.cfgImage.indexOf("file://") === 0 ? root.cfgImage : "file://" + root.cfgImage
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: true
        smooth: true
    }

    // ---- дешборд: двойная буферизация ----
    // Одна Image с cache:false на время загрузки нового файла остаётся пустой —
    // это и давало моргание раз в 2 секунды. Поэтому картинок две: новый кадр
    // грузится в скрытую и показывается только по статусу Ready, поверх старой.
    // Видимого пустого кадра не возникает ни разу.
    Item {
        id: holder
        property bool showA: true

        width:  showA ? imgA.width  : imgB.width
        height: showA ? imgA.height : imgB.height

        x: root.cfgCorner.indexOf("left") >= 0
           ? root.cfgMargin : root.width - width - root.cfgMargin
        y: root.cfgCorner.indexOf("top") >= 0
           ? root.cfgMargin : root.height - height - root.cfgMargin

        Image {
            id: imgA
            cache: false
            asynchronous: true
            smooth: false
            visible: holder.showA
            width:  sourceSize.width  / root.dpr
            height: sourceSize.height / root.dpr
            onStatusChanged: if (status === Image.Ready) holder.showA = true
        }

        Image {
            id: imgB
            cache: false
            asynchronous: true
            smooth: false
            visible: !holder.showA
            width:  sourceSize.width  / root.dpr
            height: sourceSize.height / root.dpr
            onStatusChanged: if (status === Image.Ready) holder.showA = false
        }
    }

    Timer {
        interval: 2000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            // грузим всегда в ту картинку, которая сейчас не видна
            var back = holder.showA ? imgB : imgA
            back.source = "file://" + root.cfgData + "?t=" + Date.now()
        }
    }
}
