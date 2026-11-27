// The settings window (Tools > Moment Replays). Pages on the left like OBS's own Settings; every change applies
// at once. Colours come from OBS's palette, so the window follows the OBS theme.
#pragma once
#include "core/settings.h"

#include <QAbstractButton>
#include <QDialog>
#include <QPushButton>

class QButtonGroup;
class QStackedWidget;
class QVBoxLayout;

namespace mr {

class Plugin;

class ToggleSwitch : public QAbstractButton {
	Q_OBJECT
public:
	explicit ToggleSwitch(QWidget *parent = nullptr);
	QSize sizeHint() const override { return {40, 20}; }

protected:
	void paintEvent(QPaintEvent *) override;
};

// Shows a hotkey; a click makes it wait for the next key press, Esc cancels.
class KeyButton : public QPushButton {
	Q_OBJECT
public:
	KeyButton(Plugin *plugin, std::string hotkey, QWidget *parent = nullptr);
	void show_binding();
	const std::string &name() const { return hotkey; }

protected:
	void keyPressEvent(QKeyEvent *event) override;
	void focusOutEvent(QFocusEvent *event) override;

private:
	Plugin *plugin;
	std::string hotkey;
	bool capturing = false;
};

class SettingsWindow : public QDialog {
	Q_OBJECT
public:
	SettingsWindow(Plugin *plugin, QWidget *parent);
	void save_shots(const QString &folder); // tests: every page as a PNG
	std::string self_test();                // tests: operates the controls; returns what it did

private:
	void build();   // all pages, in the current language
	void refresh(); // everything that shows live state
	void commit(const std::function<void(Settings &)> &change);
	QWidget *page_overview();
	QWidget *page_folders();
	QWidget *page_naming();
	QWidget *page_hotkeys();
	QWidget *page_sounds();
	QWidget *page_moments();
	QWidget *page_updates();

	Plugin *plugin;
	QStackedWidget *pages = nullptr;
	QButtonGroup *nav_group = nullptr;
	int current_page = 0;
	bool building = false, rebuild_queued = false;
	std::vector<std::function<void()>> refreshers;
};

} // namespace mr
