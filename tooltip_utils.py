import tkinter as tk

class ToolTip(object):
    """
    Create a tooltip for a given widget.
    """
    def __init__(self, widget, text='widget info', bg='#FFFFEA', fg='black', font=("tahoma", "8", "normal")):
        self.widget = widget
        self.text = text
        self.bg = bg
        self.fg = fg
        self.font = font
        self.tooltip_window = None
        self.id = None
        self.x = self.y = 0
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave) # Hide tooltip on click

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self.id = self.widget.after(500, self.showtip) # Delay before showing

    def unschedule(self):
        id = self.id
        self.id = None
        if id:
            self.widget.after_cancel(id)

    def showtip(self, event=None):
        x, y, cx, cy = self.widget.bbox("insert") # Get widget bounds
        x += self.widget.winfo_rootx() + 25      # Position tooltip below and to the right
        y += self.widget.winfo_rooty() + 20

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True) # Remove window decorations
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background=self.bg, relief='solid', borderwidth=1,
                         foreground=self.fg, font=self.font, wraplength=300) # Wraplength for multi-line
        label.pack(ipadx=5, ipady=3) # Internal padding

    def hidetip(self):
        tw = self.tooltip_window
        self.tooltip_window = None
        if tw:
            tw.destroy()

if __name__ == '__main__':
    root = tk.Tk()
    btn1 = tk.Button(root, text="Button 1")
    btn1.pack(padx=10, pady=5)
    ToolTip(btn1, "This is button 1's tooltip text.")

    entry1 = tk.Entry(root)
    entry1.pack(padx=10, pady=5)
    ToolTip(entry1, "Enter some text here. This is a longer tooltip to show wrapping.")

    root.mainloop()
